# UAT enhancement backlog

Synthesised from persona runs. Every item here has been read against the source; the raw findings
live in `uat/runs/<run-id>/feedback.jsonl` with a `verification` block stamped on each one.

**Nothing enters this backlog on a persona's word alone.** In the first run, three of the four
reported blockers did not reproduce — they were the UAT browser automation failing to deliver clicks
that a real mouse delivers. Had they been taken at face value they would have occupied the top of
this list while the genuine gaps waited behind them. The verification pass is not ceremony.

| Runs synthesised | Findings | Confirmed | Partly | Not reproduced | Works as designed | Unverified |
|---|---|---|---|---|---|---|
| `2026-08-03_pro-investor-01` | 28 | 13 | 4 | 5 | 3 | 3 |
| `2026-08-10_pro-investor-01` | 17 | 9 | 1 | 5 | 2 | 0 |
| `2026-07-06_pro-investor-01` (run 3) | 2 | 1 | 1 | 0 | 0 | 0 |
| `2026-07-13_pro-investor-01` (run 4) | 21 | 18 | 2 | 1 | 0 | 0 |
| `2026-07-20_pro-investor-01` (run 5) | 2 | 2 | 0 | 0 | 0 | 0 |
| `2026-07-27_pro-investor-01` (run 6) | 6 | 5 | 1 | 0 | 0 | 0 |
| `2026-06-22_pro-investor-01` (run 7) | 10 | 10 | 0 | 0 | 0 | 0 |
| `2026-06-08_pro-investor-01` (run 8) | 5 | 5 | 0 | 0 | 0 | 0 |
| `2026-06-01_pro-investor-01` (run 9) | 10 | 9 | 1 | 0 | 0 | 0 |
| `2026-06-15_pro-investor-01` (run 10) | 9 | 8 | 0 | 0 | 1 | 0 |
| `2026-06-29_pro-investor-01` (run 11) | 11 | 10 | 1 | 0 | 0 | 0 |
| `2026-05-18_pro-investor-01` (run 12) | 9 | 7 | 1 | 0 | 1 | 0 |
| `2026-08-25_orchestrated-pass` (run 14) | 4 | 1 | 1 | 1 | 0 | 1 |

*Run 1's counts are as synthesised on 2026-08-12 and left as the record of that pass. Its three
`unverified` have since been checked against the source (items 8–10 below): one confirmed, one not
reproduced, one split.*

**Run 2 (2026-08-10 → 08-13, four sessions) closed every run-1 item it re-tested and found nine new
confirmed defects.** All nine are now fixed, and **every finding in the run carries a verdict with
nothing left open** — six fixed between sessions and re-tested by the next one, three closed
afterwards. Its findings are in `uat/runs/2026-08-10_pro-investor-01/feedback.jsonl`; the items are
§R2 below.

**Status: every reported defect across eight runs is closed, with one pre-existing gap left open by
deliberate choice and one left unfixed on purpose.** Run 1's two P0s were fixed on 2026-08-12, its
five P1s and three P2s on 2026-08-14; run 2's nine confirmed defects the same day; the four defects
runs 3–5 found on 2026-08-16 (commits `b61b198`, `4648a00`); the three defects runs 6–8 found on
2026-08-17 (`c5a6b97`). One exception is `wb-margin`'s negative settled cash — pre-existing, found
while verifying runs 3–5, not caused by any of this work, and recorded under §R3-5 as a decision
still to be made rather than a bug to fix blind. The other is
`tax-disposal-gain-loss-ignores-standalone-fee-transaction` (§R6-8): the code gap is real, but every
standalone fee row seen in a real ledger is account-level and none is a selling cost, so fixing it blind
would misattribute an account-level fee against an unrelated sale — left open with the reasoning recorded
rather than guessed at. Details are kept in place rather than deleted, so a later run can re-test
them and so the reasoning survives.

**Run 1's items have now been re-tested by a persona three times, and they held every time.** Run 2
confirmed the cash and equity work, the activity view, the rule-grammar hints, the `/rules` page and
real 404, the empty-ledger onboarding and the tax-year copy. Run 4 — a full independent five-session
week, replayed against its own isolated sandbox — re-tested sixteen of those same surfaces and every
one still held. Run 7, in a third independent sandbox that had never carried any of the fixes,
re-tested cash-and-equity, lot-selection disclosure and the portfolio statement export cold, and they
held again. That is the loop closing for the third time; see §R6-8.

**Run 9 should re-test the three items fixed by `c5a6b97`** (below, §R6-8) — the drawdown card now
shared between `/report` and `/backtest`, the event-study placeholder, and the rule validator's
arity/range check — then exercise what run 6 could not: a ledger with more than one open wash-sale
window (urgency ordering) and one whose window genuinely closes during the replay (the closed-window
safe-from date, against real data rather than a unit test). It should also go after what is still
open: `wb-margin`'s negative settled cash, and a settlement-date-correct market feed or an explicit
as-of control — unchanged since run 2 asked for it and now reinforced by every run since.

*(In the event, runs 9–11 were sent at a different priority — first persona exposure to the new
Institutions tab, shipped in `d796b08` after this pointer was written — and the `c5a6b97` re-test
above was picked up by run 11 instead, cold, alongside a re-test of the tax-year default. All four
held. See §R9-11 below for what runs 9–11 actually found, and for run 12's pointer.)*

---

## P0 — blocks the product's own stated job

### 1. ~~The portfolio has no cash, and therefore no equity and no performance~~ — FIXED

**Verdict:** confirmed · **Raised:** 5 times across 4 of 5 sessions · **Surface:** API + UI
**Source:** `backend/app/api/portfolio.py` (`PortfolioReport`), `frontend/src/pages/Portfolio.tsx`

`PortfolioReport` declared no cash field, no settled-cash field and no total-equity field. The UI
cannot render what the model does not carry. The ledger *did* hold the cash movements — `CASH_IN`,
`CASH_OUT` and the `ACH` deposit are all in the sandbox ledger — but nothing aggregated them.

The consequence compounded. With no cash there is no equity; with no equity there is no period
return; with no period return there is no answer to "the sleeve was $10,000 on Monday, what is it
now?" The persona ended the week holding $4,068 in cash — 40% of the account — that the portfolio
page never once displayed, and closed with: *"I cannot see my deployment capacity on the main
portfolio view."*

**What shipped.** A new pure module, `backend/app/core/cash.py`, sums the ledger's cash movements
per account and — this turned out to be the substance of the work — decides whether the export
behind them can support a balance at all.

A naive `SUM(amount)` over a real ledger is not merely imprecise, it is fiction. Measured on real exports:

| Account shape | Naive balance | What it actually is |
|---|---|---|
| Webull accounts | arbitrary, can be large and either sign | Sells minus buys. Webull's adapter emits **only** `BUY` and `SELL` — no deposits, dividends, interest or fees. The sum **invents cash that does not exist**. |
| `rh-taxable` | positive and plausible-looking | Looks plausible, and is not. Rewind past the export's final day (a handful of sales) and the account sits below zero. |

So the module returns a **verdict, not just a total**, and withholds the figure whenever it cannot
stand behind it — `NO_FUNDING_ROWS` (trades but no external cash movement) or
`NEGATIVE_IN_CASH_ACCOUNT` (the *running* balance goes below zero in an account that cannot hold a
debit). Both are decided from the data, not from an adapter name, so an adapter that gains cash rows
later starts deriving with no change here. The running-minimum check is what catches `rh-taxable`; a
closing-balance check passes it and publishes a number that is wrong.

On a real ledger every account is therefore withheld — each with a specific,
actionable reason including *how much* opening cash the export is missing and *when* it first went
negative. That is the honest answer, and it tells the user exactly what to re-export. On a complete
export (the UAT sandbox) cash derives cleanly and agreed to the cent with the paper broker's
independently tracked figure: **$4,068.33 / $3,017.88 settled / $1,050.45 unsettled**.

`total_equity` is withheld unless *both* halves are complete. Unlike a partial market value or a
partial cash total — each still useful with the gap named — an equity figure is read as *the* answer
to "what is this worth", and there is no honest partial version of it.

Also: the positions table's `Weight` column now reads **"Weight (of invested)"**. It is a share of
priced market value, so it sums to ~100% while cash sits outside it — which is precisely why the
persona, holding 38% cash, concluded the cash was missing from the book rather than from the
denominator.

**Tests:** `tests/test_cash.py` (26), `tests/test_portfolio_api.py::TestCashAndEquity` (6).

### 2. ~~There is no transaction history, anywhere~~ — FIXED

**Verdict:** confirmed (and understated by the persona) · **Surface:** API

The persona reported that the tax page showed its one sale but not its five buys. The truth was
broader: **no transaction or activity endpoint existed in the API at all.** The only route under
`/api/portfolio` returned the positions report.

Worth escalating beyond the persona's framing, because provenance is the application's stated design
premise — `Transaction` cannot be constructed without the import and row it came from, specifically
so every figure can be walked back to a line in a broker CSV. That chain was built and maintained all
the way to the database and then never exposed. The one user who came looking for it could not find
it.

**What shipped.** `GET /api/portfolio/transactions` (`backend/app/api/transactions.py`) returns
stored ledger rows — no replay, no pricing — filtered by account, symbol, action, date range or
trades-only, paged, with `import_id` and `source_row` on every row. Being the only endpoint that
returns stored rather than derived state makes it the reference the derived endpoints can be checked
against, which is most of its value.

Aggregates (`total_bought`, `total_sold`, `net_cash_flow`) are computed across the whole filtered
set, not the page — the mistake a client makes for itself the moment it tries to sum the rows it can
see.

A new **Activity** page renders it, with the provenance coordinate on each row. The persona's week
now reads back in full: deposit, five buys, one sell, one fee.

**Tests:** `tests/test_transactions_api.py` (25).

---

## P1 — correct underneath, unusable at the surface

All five **fixed** (2026-08-14). Kept in place rather than deleted so the next run can re-test them.

### 3. ~~The rule grammar's error message hides the feature it is rejecting~~ — FIXED

**Verdict:** partly confirmed · **Surface:** API/UI · **Source:** `backend/app/rules/grammar.py:526`

The persona tried `sma20 > sma50`, was rejected, and concluded the engine only supports raw OHLCV —
calling it *"a deal-breaker for a momentum trader"* and abandoning the analysis. Verified against the
parser directly:

| Expression | Result |
|---|---|
| `sma20 > sma50` | rejected — *"unknown price field 'sma20' — valid fields are open, high, low, close, volume"* |
| `sma(20) > sma(50)` | **parses** |
| `rsi(14) < 70` | **parses** |

The full indicator registry is available; it takes call syntax. The message enumerates the five price
fields and never mentions that indicators exist or how to invoke them, so it actively teaches the
wrong conclusion. A user who reads it has no path to the working form.

**What shipped.** `_unknown_identifier_message` in `grammar.py`, ordered most-specific first:

| Typed | Now says |
|---|---|
| `sma20` | *unknown price field 'sma20' — did you mean **sma(20)**? Indicators take their parameters in parentheses, not glued to the name* |
| `sma` | *indicator 'sma' must be called with parentheses, e.g. **sma(20)*** |
| `bb_lower` | *'bb_lower' is the 'lower' output of 'bb' … e.g. **bb_lower(20, 2.0)*** |
| `opne` | *unknown price field … valid price fields are …; **indicators are called with parentheses, e.g. sma(20)**, and the registered ones are atr, bb, ema, …* |

Suggestions use the number the user typed where there is one, and the spec's defaults otherwise, so
the hint is always paste-able rather than a shape to decode. The general branch keeps the original
"unknown price field" opening — `adj_close` is a real column on a bar, just not one the DSL exposes,
so that reader *was* reaching for a price field — and appends what was missing: that indicators exist
at all.

`tests/test_rule_grammar_hints.py::TestEveryHintParses` sweeps every registered indicator through all
three malformed shapes, extracts whatever call was suggested and feeds it back through the parser.
32 hints, all parse. A suggestion that does not itself parse is worse than none: it converts a user's
correct suspicion that they mistyped something into a belief that the engine is broken.

**Tests:** `tests/test_rule_grammar_hints.py` (12).

### 4. ~~Rule editing is unreachable except by accident, and the wrong URL lies about it~~ — FIXED

**Verdict:** partly confirmed · **Surface:** UI · **Source:** `frontend/src/App.tsx:36,45`,
`frontend/src/pages/Ticker.tsx:314,318`

There is no `/rules` route and no Rules page — the persona was right about that. But the feature is
not missing: `DecisionTable` and `RuleEditor` are both mounted on `/ticker/:symbol`. Two separate
problems produced the wrong conclusion:

- **Discoverability.** Rule editing is reachable only after choosing a symbol, and nothing in the
  navigation indicates it exists. A whole phase of backend work is one unadvertised scroll deep.
- **The silent catch-all.** `<Route path="*">` redirects unknown paths to `/portfolio` with no
  message. `/rules` is indistinguishable from a feature that was never built, which is exactly the
  inference the persona drew.

**What shipped.** Both halves:

- **A real 404** (`frontend/src/pages/NotFound.tsx`) replaces `<Route path="*" element={<Navigate to="/portfolio">}>`. It names the path that failed and lists every real destination. A guessed URL is a question, and answering it by quietly showing something else is the one response indistinguishable from "no".
- **A `/rules` page** with a nav entry, carrying the rule catalog and the expression tester. The split from the ticker page is deliberate: rule *definitions* are symbol-independent (`close > sma(20)` means the same thing anywhere), while rule *evaluation* is not, so the decision table stays where the symbol already is and this page links to it.

### 5. ~~Lot selection is correct and invisible~~ — FIXED

**Verdict:** confirmed · **Surface:** UI

The persona held two XLE lots (32 @ $58.72, then 10 @ $57.73), sold 18, and had to reverse-engineer
the arithmetic to learn which lot was relieved — basis of $1,056.96 on 18 shares implied the $58.72
lot, therefore FIFO. Neither the tax page nor the disposal record stated the lot or the method.

**What shipped.** `Disposal` gains `lot_method`, carried through `GainRow` to the API alongside the
`lot_id` that was already computed and never exposed. It is `None` — not `"fifo"` — on an oversold
shortfall, where the replay found no lot to consume: defaulting that row to FIFO would assert a
selection was made over lots that do not exist.

The Tax page gains a **Disposals** table. `gains.rows` was previously computed, carried across the
API and never rendered — the page went straight from summary tiles to the Form 8949 boxes, so the
ordinary question "which shares did I just sell?" had no answer on screen. Each row now reads
`0cf450e6 · FIFO` with the acquiring lot's date beside it. Form 8949 deliberately does *not* carry
these columns; it mirrors the IRS layout, and a lot id is not part of that form.

### 6. ~~No portfolio statement export~~ — FIXED

**Verdict:** confirmed · **Surface:** workflow · **Source:** `backend/app/api/report.py:165`,
`backend/app/api/tax.py:54`

`/api/report/export` produces a per-symbol research narrative; `/api/tax/form8949.csv` produces a tax
form. Neither is a statement of positions, basis, cash and valuation as of a date — the artifact a
professional produces at the end of a week.

**Unblocked by the P0 fixes** — a statement without cash is not a statement.

**What shipped.** `GET /api/portfolio/statement.md` renders holdings, cost basis, valuation, cash
(settled and unsettled) and equity as Markdown, with a **Download statement** control on the
portfolio page. Markdown rather than CSV, matching `/api/report/export`: a document to read or
archive, not a table to paste (Form 8949 already covers that).

**Every caveat travels inside the file.** An exported document outlives the screen it came from, so
unpriced symbols and each account whose cash could not be derived are written into a *Completeness*
section at the top rather than left behind in the UI. Absent figures render `—`, never `$0.00`. On
a real ledger the statement opens with several caveats and states plainly that no equity figure is
available; on a complete export that section is absent entirely.

**Tests:** `tests/test_portfolio_api.py::TestStatementExport` (5).

### 7. ~~The portfolio total carries no as-of~~ — FIXED

**Verdict:** partly confirmed (narrowed) · **Surface:** UI
**Source:** `frontend/src/pages/Portfolio.tsx:443`, `:149`

The persona's complaint was broader than what survives verification. The page already did two things
well: each position row renders `as of <date>`, and a prominent banner declares when totals are
partial and names the excluded symbols. What had no as-of was the **summary total** — the first
figure read, and the only one that silently aggregates several different price dates.

**What shipped.** A stamp above the tiles, which adapts to what it is describing:

- one pricing date — *Ledger as of 2026-08-06 · priced at the close of 2026-08-13*
- several — *…priced at closes ranging 2026-08-11 → 2026-08-13 — the market-value and unrealized totals below mix 3 different pricing dates*
- none priced — *…nothing is priced, so no market value is stated*

Derived on the client from the `price_as_of` already on each position rather than added as a server
field, so it cannot disagree with the rows it summarises.

---

## P2

All three closed 2026-08-14. Two of them were **understated** by the persona and one was two
findings wearing one id — which is the argument for verifying against the source rather than
triaging on the report alone.

### 8. ~~Import has no UI affordance~~ — FIXED, and it was worse than reported

**Verdict:** partly confirmed · **understated.** The persona said the instruction — drop files into
`data/` — had no interface. True. The larger fact was that it had no *implementation*: `app.ingest`
was reachable from tests and the UAT harness and from nothing in the running application, so the
"rebuild" every empty state named did not exist in any form, UI or otherwise.

Fixed by `python -m app.ingest`, `GET`/`POST /api/import` and an Import panel on the Activity page.
See `docs/reports/import-path.md`. Wiring it up also found a `record_raw_rows` that had never been
called and crashed on every real Robinhood file, which is why `raw_row` was empty in a real ledger.

### 9. ~~Empty tax year renders a blank panel~~ — NOT REPRODUCED; the copy was wrong

**Verdict:** not reproduced. `Tax.tsx` has an explicit `empty` phase and has always rendered a
message, not a blank panel.

But the message was wrong in a case the persona did not reach: it read *"No data imported for
{year} yet"* whenever a year's collections were empty — including for a user with a full ledger and
no activity in that year, who was then told to go and import data they already had. The two states
are now distinguished, with the ledger's row count named in the second. Fixed 2026-08-14.

### 10. ~~Macro snapshot as-of and component units~~ — one half confirmed, one half not

**Verdict:** split, and it should have been two findings.

- **As-of: not reproduced.** The page stamps `generated {snapshot.generated_at}`, every tile carries
  its own `as_of`, and the Fear & Greed gauge carries one too. Closed.
- **Component units: confirmed.** `FearGreedComponent.raw_value`'s own docstring says the seven
  components are *"not comparable across components"* while the gauge rendered them as seven bare
  decimals under a column headed **Raw** — an S&P 500 level, a put/call ratio and a credit spread on
  adjacent rows. Each now carries its unit and a description: `7,781.89 index`, `0.71 ratio`,
  `1.21 pp`. Fixed 2026-08-14, see `docs/reports/round-4.md`.

---

## §R2 — run 2 (`2026-08-10_pro-investor-01`)

Four sessions, seven positions, +0.98% against SPY's +0.63% — the P&L is noise over four days and is
not the point. **Every run-1 item the persona re-tested came back fixed**, and the run's own defects
were fixed between sessions and re-tested by the next one, which is the loop working as designed
rather than a backlog being filled.

### The theme, stated first

**Eight of the nine confirmed defects were a number computed correctly under a label that meant
something else.** Not arithmetic errors — the persona checked the arithmetic in session 3 and it held
to the cent. Labels: a cash split whose "settled" exceeded the balance, a tax message asserting a
count it never took, drawdown rows describing two different episodes under one heading, and a
"Current drawdown" that reports the worst point of the ongoing episode rather than where the price
is now. The persona's closing verdict names it before the fix list does: *"a real number computed
correctly but not meaning what its label implies is the single biggest recurring theme across all
four sessions"*.

That is a harder class to test for than a wrong figure, because every unit test passes.

### Fixed inside the run

| # | Finding | What it was |
|---|---|---|
| R2-1 | `portfolio-settled-unsettled-cash-split-incorrect` | `unsettled` summed purchases as well as proceeds, so `settled = balance − unsettled` **exceeded the balance**: $10,000.00 settled reported on an account holding $2,981.86. Now proceeds only, with `settled <= balance` pinned as an invariant. The persona named the cost exactly: that is the figure someone sizes a position against. |
| R2-2 | `tax-year-activity-message-contradicts-transaction-count` | The Tax page said "none of them in this tax year" about a ledger whose every row *was* in that year — asserted from the total row count, never having counted the year. Three cases now, the third counted from the transactions endpoint. Introduced by round 3A. |
| R2-3 | `tax-year-zero-disposals-boilerplate-contradicts-transactions-shown` | The fix for R2-2 left a trailing "this is an absence of data, not a report of zero gains" on all three cases, contradicting the one where the year genuinely has activity and genuinely has zero gains. |
| R2-4 | `portfolio-api-money-fields-carry-float-precision-noise` | `"market_value": "1555.7600097656250"`. The bar store holds float32; `777.8800048828125` is the image of a $777.88 close, and `Decimal(str(...))` preserved it — under a comment claiming that hop *avoided* the imprecision. A violation of this project's first standing decision, caught by a user rather than by the four tests that guard it. |
| R2-5 | `activity-import-panel-transient-500` | A genuine race: `load_builtin_adapters` read a process-global then mutated it with no lock, and round 3A put it on a request path served from a thread pool. "Transient, self-resolved on reload" is what that looks like from outside. |
| R2-6 | `rules-tester-placeholder-example-does-not-parse` | The expression field's own placeholder used colon syntax the DSL has never accepted. The same commit that added helpful hints for mistyped indicators shipped an example that produced a raw tokenizer error. |
| R2-7 | `report-drawdown-facts-table-still-underwater-contradicts-current-drawdown` | "Still underwater: no" two rows from "Current drawdown −15.6%". Both true, of different episodes, neither labelled. |

### ~~R2-8 · `report-current-drawdown-frozen-at-episode-trough-not-live-price`~~ — FIXED 2026-08-14

Confirmed, **major**, and the reason the persona's verdict was "not yet".

`_episode` computed `depth = trough / peak − 1` for every episode including the still-open one, so
*Current drawdown* reported how bad the ongoing episode got at its worst, not how far below the peak
the instrument is today: **−15.6% on XLE**, **−16.0% on XLK**. Both figures are worth having; the
label named only one of them, and it was the one it did not compute.

**What shipped.** `DrawdownEpisode` gains `depth_now` (peak to the latest observation),
`last_value` and `last_value_date` — all `None` on a recovered episode, because one that ended has
no position today and `0.0` would claim it is sitting exactly at its peak. The report bundle keeps
`drawdown.current_depth` as an id — a fact id is a citation key and prose written against it must
keep resolving — and now carries the figure that label always promised, with the old number beside
it as `drawdown.current_episode_worst` and an as-of on both.

Measured after: **XLE −15.6% → −2.40%**, **XLK −16.0% → −3.75%**, each against the 2026-08-13 close.

Two decisions worth recording. For `INTRADAY`, "now" is measured on the **peak column** (`high`) —
the one the recovery test uses, so the question is asked with the measure that would actually end
the episode; answering on `low` would report the latest bar's worst excursion as the current
position. And a missing final print falls back to the last *valid* observation, dated honestly,
rather than reading a NaN as a price — the module's standing rule that a gap never silently
participates in a figure.

The card shows the low as `fell 15.6% to its low on 2026-07-01` rather than as a second labelled
percentage: `formatDepth` drops the sign by convention, and two bare percentages stacked on one card
read as two estimates of the same quantity that disagree — which is the confusion this change exists
to remove, reintroduced one line lower.

### ~~R2-9 · `decision-table-significance-rating-has-no-explained-threshold`~~ — FIXED 2026-08-14

Confirmed, minor, and closed by the definitions pass. `DecisionTable` now carries a `criteria`
block built from the constants in `app.rules.evidence`, and the table renders a legend from it —
*suggestive* needs ≥30 independent triggers **and** ≥8 points of edge, *weak* ≥8 and ≥15 points,
both conditions together. The numbers travel from the backend rather than being restated in the
component, so the legend and the rule cannot drift; the API shape test asserts the field exists.

### ~~R2-10 · `portfolio-derived-state-not-built-badge-unexplained`~~ — FIXED 2026-08-14

Partly confirmed, and the decision it needed was made: **`derived_build` has no future, and is
dropped** (schema version 3).

It recorded rebuilds of materialised lots, positions and gains — tables the design moved away from.
Every derived figure is recomputed from the ledger per request, deliberately, because a cache that
can silently disagree with the ledger underneath it is how a tax page shows figures that are no
longer true. So nothing ever wrote it, the endpoint reported `never_built` for the life of the
application, and the badge sat beside figures that were correct.

Removed rather than reworded, and **nothing replaced it** — filling the hole is how the next
unexplained badge arrives. Two tests that inserted into the table and asserted "stale" and "current"
are gone with it: a test exercising a state the system cannot reach is not coverage, it is a claim
that the state matters.

The migration drops the table **only when empty**, checked rather than assumed. The performance
premise was measured rather than trusted: the full replay of a real ~1,000-transaction ledger is
a fraction of a second, most of it wash-sale matching — which also corrected `app/api/tax.py`'s docstring,
which had claimed "milliseconds" without anyone timing it.

### ~~R2-11 · `backtest-event-study-no-technical-indicators`~~ — NOT AN OPEN ITEM (2026-08-14)

**Nothing to fix. This entry was my error, and it is the same error this whole section catalogues.**

I wrote "unverified, carried" from the *id* without reading the body. The id is run 1's, filed for
*"Event Study condition parser rejects SMA, only accepts raw OHLCV"*. Run 2's persona reused it —
**correctly**, same root cause — to report that it is fixed. What it did not do was title the
re-test after the original problem: it named the surface it happened to check (the `/rules`
expression tester), so the entry read as an open event-study gap to anyone going by id and title.

Verified properly, which is what should have happened before it was carried. `POST
/api/backtest/event-study` with `conditions: ["close < sma(20)", "rsi(14) < 40"]` against SPY:

```
close < sma(20)   guard=passed   h=5  n=3084  indep=818  hit=0.571  base=0.571
rsi(14) < 40      guard=passed   h=5  n= 917  indep=302  hit=0.592  base=0.572
```

The guard's own finding reads *"sma_20: identical at every position across 8 leading slices of 8442
bars"*. The condition parser is the whole DSL, so every registered indicator is available, and
`tests/test_backtest_api.py:429` already pins it. Run 1's finding is genuinely closed.

**With this, every item from run 2 is resolved.** Eight fixed, one closed as works-as-designed, one
not reproduced, and this one closed as a mis-read record.

### A fifth harness action

The cause was structural, not carelessness on the persona's part. My session brief told it to
"reuse the existing backlog id" while `BACKLOG.md`'s run-1 items are **numbered prose**, not
`finding_id`s — so there were no ids in front of it to reuse, and it improvised from ones it had
seen elsewhere. Three of four re-tests still landed on the right id; the fourth landed on a related
one.

Fixed in the harness rather than in an instruction: `brief` now emits **`known_findings`** — every
`finding_id` any previous run recorded, with its title — so each session gets the real list
automatically and no orchestrator has to remember to paste it. Titles travel alongside because an id
on its own invites inferring the problem from the slug, which is exactly the mistake made here.

Two conventions that follow, now in the persona brief:

- **A re-test's title describes the original problem, not the surface you checked it on.** The
  `finding_id` is the dedupe key across runs; the title is what a reader uses to decide whether the
  entry is open.
- **Read the body before triaging an id.** Written for me as much as for the persona.

### What the persona would need before routing a real book through it

Recorded verbatim in intent, because it is the most useful thing the run produced:

1. ~~**A definitions pass on every headline statistic**~~ — **done 2026-08-14**, see
   `docs/reports/definitions-pass.md`. It found five further mismatches nobody had reported,
   including a sample size overstated seven-fold on hourly reports and a trade count labelled
   "closed" that included open trades. `docs/DEFINITIONS.md` is the register it produced, and
   `tests/test_definitions.py` fails when a statistic reaches a user without a stated meaning.
2. **A settlement-date-correct market feed**, or an explicit as-of control. Marks legitimately
   post-date the replayed session (a known harness caveat, see below), and *"confusing becomes wrong
   the day someone acts on a look-ahead price without noticing"*.
3. Ticker search re-tested outside synthetic clicks — see the harness note below; it is fine.
4. One more cycle against real multi-broker exports rather than the sandbox's clean one, to see
   whether the cash module's withhold-rather-than-estimate discipline holds up.

### A fourth harness action

`ticker-page-search-does-not-work` was filed **again** in session 1, and again it does not
reproduce: `.symbol-example` `.click()` and a native-setter `input` + `submit` on `.symbol-form`
both navigate correctly. The three harness fixes applied on 2026-08-14 were in place and the persona
followed the retry instruction *in spirit* while still using coordinate clicks.

So the instruction is not enough. **Give the persona the snippets, not the principle** — sessions 2
through 4 were handed the exact `javascript_tool` patterns and the finding did not recur, while
those sessions produced the run's sharpest findings instead. Also: the harness rejects a repeated
`finding_id` *within* one run, so a re-test outcome belongs in the journal and the verification
pass, not in the findings file; the session-3 brief asked for the opposite and had to be corrected.

---

## §R3-5 — runs 3–5 (`2026-07-06`, `2026-07-13`, `2026-07-20`)

Three more five-session runs, executed 2026-08-16 alongside this synthesis pass but replaying
**historical July windows** — the bar store ends 2026-08-14 and there is no forward week left to
trade. Each ran against its **own sandbox ledger** (`uat/sandbox/run3` / `run4` / `run5`, added in
commit `1ff72aa`) rather than the shared one runs 1–2 used: a July persona browsing a ledger that
also held runs 1–2's August positions would have been shown future data through the dashboard —
exactly the lookahead-through-the-price-boundary defect `AsOfMarket` exists to make impossible.
Isolation closes that hole at the ledger/dashboard boundary and, as a side effect, let all three run
in parallel instead of queueing behind one SQLite file.

| Run | Window | Sessions | Fills | Rejections | Ending equity | vs SPY |
|---|---|---|---|---|---|---|
| 3 | 2026-07-06 → 07-10 | 5 | 6 (5 buy, 1 sell) | 0 | $10,001.96 (+0.02%) | +0.49% |
| 4 | 2026-07-13 → 07-17 | 5 | 7 (5 buy, 2 sell) | 0 | $9,979.64 (−0.20%) | −0.78% |
| 5 | 2026-07-20 → 07-24 | 5 | 10 (8 buy, 2 sell) | 7 | $9,921.64 (−0.78%) | −0.43% |

These are five-session samples and say nothing about the persona's process — `metrics.json`'s own
`$comment` says so on all three runs, and it is repeated here rather than assumed.

### The loop closing, for the second time

**Seventeen of run 4's twenty-one findings reuse a run-1 or run-2 `finding_id`. Sixteen came back
`confirmed` — the fix still working — and the seventeenth is `thesis-page-buttons-dont-load`, which
has now failed to reproduce twice. Nothing regressed.** The remaining four are new: the two defects
fixed in `b61b198` and the two wash-sale disclosure gaps that narrowed under verification.

*(An earlier draft of this section said "eighteen re-tests, all held". Eighteen is run 4's count of
`confirmed` findings, which is not the same set — it includes the two new defects it filed. The
re-test count is sixteen. Recorded rather than silently corrected, because a miscount in the
direction of "more evidence than we have" is the kind this file exists to catch.)*

Nothing regressed across three independent weeks
of replay, executed 2026-08-16 against isolated sandboxes and reusing none of runs 1–2's state. That
is the single most important result of this pass: the P0/P1/P2 fixes and the §R2 fixes hold up
against a fresh persona's own five-session week, not just a repeat of the exact steps that found them.

The one `not-reproduced` in the three runs is `thesis-page-buttons-dont-load`, filed as a blocker by
run 1 and already carried there as not-reproduced. Run 4's session 2 drove it again with real
`.click()` events — five trials ran, all `INCONCLUSIVE`, with a populated trial ledger and a
holdout summary. It has now failed to reproduce **twice**.

### Four defects were open. All four are now fixed (`b61b198`, `4648a00`).

#### 1. ~~`tax-page-defaults-to-wrong-year`~~ — FIXED

**Verdict:** major, confirmed · filed **independently by all three runs**.
**Source:** `frontend/src/pages/Tax.tsx:139-140`

`useState(currentYear - 1)` opened the page on 2025 against a ledger holding only 2026 rows —
defensible in January, wrong the rest of the year. Every persona that hit it read the empty year as a
failed import rather than a wrong default, which is what makes it major rather than cosmetic: run
5's persona put it plainly — *"there is no visual cue that 2025 was chosen for me rather than by
me... a user who trusts the first screen and doesn't think to check the dropdown walks away believing
tax tracking is broken."*

**What shipped.** The year now resolves from the most recent transaction's trade date, falling back
to `currentYear - 1` only on an empty ledger. The selector is held back until it resolves, so it
cannot render one year and silently swap to another.

**Merge note.** Run 3 filed the same root cause as `tax-page-defaults-to-year-with-no-activity`.
Both personas noticed the id collision themselves and neither re-filed under it a second time.
`tax-page-defaults-to-wrong-year` (run 4's and run 5's id) is canonical — it names the default
rather than the symptom. `tax-page-defaults-to-year-with-no-activity` is dead; a later run should
not treat it as a separate open item.

#### 2. ~~`cash-settled-unsettled-split-fee-misattributed`~~ — FIXED

**Verdict:** minor, confirmed · filed by **runs 4 and 5**.
**Source:** `backend/app/core/cash.py:450-460, :470`

`unsettled` filtered on `t.amount > 0`, admitting a pending sale's gross proceeds while excluding the
negative fee row sharing its settle date — so `settled = balance - unsettled` came out short by
exactly the fee. Run 4's persona observed it first on a $0.03 XLV fee (settled short by $0.03 of the
true figure). Verification reproduced it independently on two more fee amounts, scaling exactly with
the fee each time: $0.02 on TLT (settled `1750.66` reported vs `1750.68` true, run 5, also confirmed
against the paper broker's own `book_after.settled_cash`) and $0.06 on QQQ (run 4, session 2's QQQ
sell).

Two things worth keeping on the record. This is **not a harness artifact** — `ingest/adapters/
robinhood.py` maps `FEE` and `EMRF`, `sofi.py` maps "transfer fee", so real broker exports carry
standalone fee rows too, and a real balance inside the T+1/T+2 settlement window is exposed to the
same bug. And the **first fix attempt reopened the original defect through a different door**:
filtering on `action is not BUY` would have let a pending `cash_out` or `transfer_out` sum into
`unsettled` and push `settled` above `balance` — a real ledger holds such rows (a large pending
withdrawal and a large pending internal transfer). The shipped fix classifies all 17 `TxnAction` members deliberately and withholds the
split rather than ever publishing a negative `unsettled`.

#### 3. `wash-sale-repurchase-safe-date-not-displayed` — FIXED, narrowed under verification

**Verdict:** major as filed, **partly-confirmed** · filed by **runs 3 and 4**.
**Source:** `frontend/src/pages/Tax.tsx:756-767`, `backend/app/tax/washsale_summary.py:140-142`

The claim as filed — "the frontend never renders the repurchase-safe date" — is false: the
open-window branch renders `{days_until_safe} days — safe from {repurchase_safe_on}` and always did.
The date was dropped only once the window closed, where a bare "safe to repurchase" badge showed
while the caption below it still promised a date. Both personas landed in the closed branch because
`window_is_open` is computed from the real clock while the replay is July, so every July window had
long since closed by 2026-08-16.

**What shipped.** The closed-window branch now renders the same date the open branch always did.

#### 4. `wash-sale-tolled-holding-period-not-displayed` — FIXED, narrowed under verification

**Verdict:** minor, **partly-confirmed** · filed by run 4.
**Source:** `frontend/src/pages/Tax.tsx:342-350`, `backend/app/tax/`

Tolling *was* rendered — on disposal rows, as `(holding from {holding_start})`. A replacement lot
that absorbed a disallowed loss and is **still held** never appears in the disposals table, so its
tolled holding period reached the user nowhere. Real gap, narrower than filed: the arithmetic was
never wrong, only invisible for a lot nobody had sold yet.

**What shipped.** Keyed on every `replacement_lot_ids` entry rather than on `basis_added_to_lot_id`
— that field names only the lot that absorbed the *most* basis, so keying on it would still hide a
still-held tolled lot whenever the largest replacement happened to be the one that was sold.
`_sync_disposals` had the same narrow keying on the backend and was fixed for the same reason.

**Two of these four narrowed under verification rather than confirming as filed** (#3 and #4 above).
That is the verification pass earning its place — the fix that shipped for each is smaller and more
precise than the one the filed report would have produced on its own.

### Two harness defects, both fixed in `4648a00`

- **Rejections were double-recorded.** `_precheck` refuses through `_reject`, which appends to
  `self.rejections`; `submit` appended the same returned object a second time. Precheck rejections
  landed twice, price-dependent ones once — selective, so `rejections_by_rule` came out wrong in a
  way that still looked plausible. It survived four runs because runs 1–4 produced **zero**
  rejections between them; run 5 was the first order the harness ever refused. `4648a00` makes
  `_reject` the sole append site. **Run 5's `metrics.json` is left as recorded, deliberately — it is
  the evidence.** It reads 7 rejections with `fractional_shares: 2`; the true figures are **6 and
  1** (confirmed directly against `state.json`'s `rejections` array, which lists order `s2-8`
  twice). Use the corrected figures, not the file, when citing run 5.
- **`stop_level: "n/a"` crashed the CLI** with an unhandled `decimal.InvalidOperation`, breaking the
  JSON-only contract every command in this CLI documents. `null`, a missing key, `""` and `"n/a"`
  now all mean no stop.

### What each run was sent to exercise, and what came back

- **Run 3** — close a position so realised gains and lot selection get persona-tested. Sold 2 QQQ
  for a $19.86 loss (session 3), rebought 2 QQQ inside the window (session 5) — a **full-disallowance**
  wash sale (Form 8949 code `W`, reportable $0.00), though the persona filed no confirmation finding
  for it directly.
- **Run 4** — generate a real wash sale deliberately. Sold 7 XLV at a $26.25 loss (2026-07-15),
  repurchased 2026-07-16, disallowed in full, rolled into the replacement lot's basis
  ($1,123.01 + $26.25 = $1,149.26 as shown on the portfolio), tolled holding period carried, Form
  8949 code `W`. Cross-checked across four surfaces (disposals table, wash-sale-by-symbol panel,
  wash-sale detail table, portfolio cost basis) by the persona and all four agreed. First
  fully disallowed wash sale a persona has produced — run 1's was partial, $3.60 of a $6.48 loss
  disallowed pro rata (see "Confirmed working" above). Run 3 produced one the same week; the two ran
  concurrently, so neither is "first" ahead of the other.
- **Run 5** — breach the mandate deliberately. **7 rejections across 5 rules** —
  `insufficient_cash` ×2, `min_clip`, `fractional_shares`, `unpriceable`, `max_single_name_weight` —
  every message specific and quantified (e.g. *"$2231.34 exceeds $1750.68 of settled cash"*). Four
  of the five were manufactured on purpose to exercise the rule; the `max_single_name_weight` one was
  not — the persona's own session-4 journal calls it *"a real trade decision"*: a genuine
  trend-following add into XLE that the 25% cap correctly blocked, then sized correctly under the
  cap the next session. This rejection path had never been exercised by a persona in four runs.

### Open, not fixed, recorded for a later decision

Found while verifying, **pre-existing, and not caused by this work**: `wb-margin` reports
a negative `settled` figure against a positive balance, because unsettled exceeds the
balance. On a margin account a negative deployable figure may be legitimate — it is a debit — but
"what can I deploy" rendering negative deserves a deliberate decision rather than a silent pass.
Verified by measuring all seven accounts' cash figures before and after the §R3-5 cash-split fix:
nothing about `wb-margin`'s numbers changed, so this predates today's work and is unrelated to it.

### Harness caveat worth recording for future runs

Marks post-dated the session by **three to five weeks** this time, far beyond the one-to-two days
runs 1 and 2 saw, because the bar store runs to 2026-08-14 while the replay is July. All three
personas checked the labelling and found it honest (*"Ledger as of 2026-07-13 · priced at the close
of 2026-08-14"* plus per-row as-of stamps), and **none of them filed
`portfolio-prices-stale-without-warning`** despite being permitted one under the "works as designed"
precedent below. The same root cause reaches the wash-sale panel's window check (see defect #3
above) and the macro page. The standing open item — a settlement-date-correct feed or an explicit
as-of control — is unchanged; this is more evidence for it, not new evidence against the current
behaviour.

Also: two of the three sessions hit `preview_start` resolving `.claude/launch.json` from the parent
directory rather than the repo root, and worked around it by starting the frontend/backend servers
directly. That is an environment quirk in this harness invocation, not an application defect — note
it so run 6 does not lose time rediscovering it.

---

## §R6-8 — runs 6–8 (`2026-07-27`, `2026-06-22`, `2026-06-08`)

Three more five-session runs, executed 2026-08-17/18 in parallel against isolated sandboxes
(`uat/sandbox/run6` / `run7` / `run8`), each sent somewhere the previous five runs had not been: run
6 took the brand-new Wash Sales tab, no persona having seen it before; run 7 re-tested the runs 3–5
fixes cold, in a sandbox that had never carried them; run 8 went at the rules and backtest surfaces
five prior runs had barely touched. **21 findings, all verified: 20 confirmed, 1 partly, 0
unverified.** All three sandboxes are isolated from the shared one and from each other — the default
sandbox ledger's mtime (2026-08-14) is unchanged by any of the three runs' 2026-08-17/18 activity,
confirmed by all three personas and independently here.

| Run | Window | Sessions | Fills | Rejections | Ending equity | vs SPY |
|---|---|---|---|---|---|---|
| 6 | 2026-07-27 → 07-31 | 5 | 5 (4 buy, 1 sell) | 0 | $10,051.60 (+0.52%) | +1.07% |
| 7 | 2026-06-22 → 06-26 | 5 | 6 (4 buy, 2 sell) | 4 | $10,070.04 (+0.70%) | −2.07% |
| 8 | 2026-06-08 → 06-12 | 5 | 6 (5 buy, 1 sell) | 0 | $9,992.12 (−0.08%) | +0.34% |

As with runs 3–5, five sessions says nothing about the persona's process — `metrics.json`'s own
`$comment` repeats it on all three runs, and it is repeated here rather than assumed.

### The pattern: a fix that reached one surface and not its twin

The three genuine defects these runs found are not three unrelated bugs. Each is a fix that landed
once and needed to reach two places, and only reached one — commit `c5a6b97`'s own title names the
pattern before its diff does. That is worth leading with, ahead of any one of the three.

#### 1. ~~`report-current-drawdown-frozen-at-episode-trough-not-live-price`~~ — FIXED

**Verdict:** major, confirmed · filed by **run 7** · **Source:** `frontend/src/pages/Report.tsx:330-341`
(pre-fix), `frontend/src/components/DrawdownTable.tsx:163-170`

`/backtest` showed XLE 1.0% off its peak while `/report/XLE` showed 15.6% for the same episode on the
same day — two renderings of the same number disagreeing by 14.6 percentage points. The `depth_now`
fix that closed R2-8 on 2026-08-14 went into `DrawdownTable`'s `CurrentDrawdownCard`; `Report.tsx`
had grown its own copy, rendering `drawdown.current.depth` — the pre-fix field — and never received
it. Its own comment claimed the page "reuses the presentation," true of the CSS class names and false
of the logic underneath them, which is exactly how the two pages came to disagree the moment one of
them was corrected and the other was not: this is a genuine regression, introduced by R2-8 itself
rather than by these three runs.

**What shipped.** `CurrentDrawdownCard` is exported from `DrawdownTable.tsx`; `Report.tsx` renders it
directly instead of its own copy. One renderer, so there is nothing left to diverge.

#### 2. ~~`backtest-event-study-placeholder-uses-colon-syntax`~~ — FIXED

**Verdict:** minor, confirmed · filed by **run 8** · **Source:** `frontend/src/components/EventStudy.tsx:97`
(pre-fix), `frontend/src/components/RuleEditor.tsx:20-35`

`EventStudy.tsx`'s condition field offered `e.g. rsi:14 < 30` — colon syntax the DSL has never
accepted. `RuleEditor` had this exact defect, fixed 2026-08-14 as R2-6, and its own comment records
why it matters: a user who types the application's own suggestion and gets `unexpected character
':'` stops trusting the rest of the page. The fix never reached the event-study field, a second
surface built on the same DSL.

**What shipped.** `EventStudy.tsx` now imports and renders the shared `PLACEHOLDER_EXPRESSION`
constant instead of its own string, already pinned by `tests/test_frontend_contract.py`, which feeds
it through the real parser.

#### 3. ~~`rules-validate-accepts-arity-and-range-errors-as-valid`~~ — FIXED

**Verdict:** minor, confirmed · filed by **run 8** · **Source:** `backend/app/api/rules.py:174-189`
(pre-fix), `backend/app/indicators/base.py:276-294`, `backend/app/rules/evaluate.py:150-159`

`/rules`' expression tester reported VALID for `rsi(14, 5)` — RSI takes exactly one parameter — and
`close > sma(9999)` — SMA caps at 500 — both of which `parse_spec` refuses the moment the rule
actually runs, for arity and for range respectively. `required_specs` documents that it does not
check the registry, and `/validate` never asked it to: VALID meant "parses," not "will run." The
endpoint's own "must stay cheap" rule is about the bar store and the network; `registry.request` is
an in-memory lookup against neither.

**What shipped.** `/validate` now calls `registry.request` on every parsed spec and returns
`valid=false` with the registry's own arity/range message on failure. `test_rules_api`'s fake
evaluator, which previously returned a placeholder string the new check would itself have rejected,
now returns a real spec string, and the added test drives the real grammar and registry rather than
the fakes — what the registry says is the entire question here.

### Run 6 and the first persona look at Wash Sales

Run 6 is the first persona run of any kind to reach `/wash-sales`, added in `9ea36c9`. The persona
deliberately manufactured a wash sale to exercise it: sold 1 QQQ at a $1.42 economic loss (session
3), repurchased 1 QQQ inside the 30-day window (session 4).

**Reconciled to the cent across five surfaces.** The `/wash-sales` tab's top tile (`DEFERRED $1.40`),
its expanded QQQ card (`1 sale, $1.40 loss, $1.40 disallowed`), the Tax page's summary tile and its
"Wash sales by symbol" panel, Form 8949 (code `W`, adjustment $1.40, gain/loss $0.00), and the
portfolio's QQQ cost basis ($676.50 = $675.10 fill price + the $1.40 rolled-in loss) all agree, and
none required leaving the page to derive. Filed as a positive finding
(`wash-sale-figures-reconstructible-across-four-surfaces`), on the same principle as "Confirmed
working" below.

**The row this tab was rebuilt for reads correctly.** Before the repurchase, the QQQ row on
`/wash-sales` — an open window with nothing disallowed yet — rendered "NOT YET TRIGGERED —
REPURCHASE NOW CREATES A WASH SALE" in full words on the expanded sale row, not a bare `$0.00` that
would read as nothing-to-see. Filed as a second positive
(`wash-sale-open-window-zero-disallowed-reads-as-live-warning`).

**The scope line holds.** `WashSales.tsx`'s `ScopeLine` component states the page is scoped to the
whole connected account history, year-independent and computed against today's date — "unlike the
Tax page's own wash-sale figures... expect the two pages' totals to differ; that is not an error" —
precisely the divergence a persona comparing the two pages' totals would otherwise read as a bug.
Deferred and permanently-disallowed totals are never summed anywhere on either page; both carry an
explicit "never sum this with the deferred figure" line rather than publish a total that would
misstate an active disallowance as final.

**Two things run 6 could not test, and neither is glossed here.** The run's ledger only ever produced
one open-window symbol, so urgency ordering (open windows sorted by days-remaining) is unexercised by
any persona to date. And because `window_is_open` is computed against the real 2026-08-17 clock while
the replay's window's safe date (2026-08-29) never arrived during the replay, the window never
actually closed — so the closed-window branch's safe-from date, fixed as part of runs 3–5's
`wash-sale-repurchase-safe-date-not-displayed`, was exercised only by run 7's re-test of a
pre-existing closed window, not by run 6 against a window this tab's own persona produced. Unit tests
for both are being added concurrently with this synthesis pass, but a unit test and a reader are
different instruments — **run 9 should still exercise both against real data.**

### `tax-disposal-gain-loss-ignores-standalone-fee-transaction` — narrowed under verification, left open on purpose

**Verdict:** minor, **partly-confirmed** · filed by **run 6** · **Source:** `backend/app/core/lots.py:882-899`,
`backend/app/ingest/adapters/robinhood.py:149,155`

`Disposal.fees` is taken only from the SELL transaction's own `fees` column — confirmed directly in
`lots.py`: the SELL branch computes `per_share_fees = txn.fees / qty` and never looks at any other
row. A standalone `FEE` ledger row sharing the sale's settle date is never attributed to the disposal
it belongs to. The persona measured this on its own QQQ sale: a $0.02 fee row that the wash-sale math
(deferred amount, replacement lot basis) never subtracted, while the portfolio's settled/unsettled
cash split — fixed as `cash-settled-unsettled-split-fee-misattributed` — does account for the same
fee correctly. The two surfaces disagree about the same $0.02.

**The code gap is real. The measured impact is not**, and that is why the defect is left unfixed.
Every standalone fee row seen in a real ledger is account-level: ACAT-out fees, an early IRA
match-removal fee, a brokerage account fee and subscription fees — none carrying a symbol or
instrument, none a selling cost. No real `sell` row carries any fee at all, which is why the
application already warns `FEES_UNKNOWN` rather than silently reporting fees as zero. Attributing a
standalone fee row to a disposal needs a link these rows do not carry — guessing would charge an
unrelated account-level fee against an arbitrary sale, which is worse than the cents currently
missing. **Recorded so a later run does not "fix" this blind.**

### A process finding: run 7 filled in its own `verification` blocks

Each of run 7's ten `findings-sN.json` files carries a `verification` block with `status: "confirmed"`
already set, present before this synthesis pass touched anything — confirmed by diffing the raw
session files against the consolidated `feedback.jsonl`: identical blocks, present from the start.
`uat/schema/feedback.schema.json` describes that field as *"Filled in by the synthesis pass, not by
the persona. A persona's claim is a report until someone reads the code."* Self-certification is
exactly what the field exists to prevent — a persona confirming its own finding is not evidence, no
matter how the note reads.

Run 6 and run 8's raw session files carry no `verification` key at all, which is the correct shape;
only run 7's did. All ten of run 7's findings were re-derived here against source rather than
inherited, and the outcome happened to agree in every case — which is not the point. **The persona
brief should tell future runs to leave `verification` unset**, added to "Actions on the harness
itself" below.

### What each run was sent to exercise, and the loop closing a third time

- **Run 6** exercised the new Wash Sales tab, deliberately manufacturing a full-disallowance wash
  sale to do it (see above), and re-tested three previously-fixed items cold: the tax-year default,
  the settled/unsettled fee split, and the tolled holding period. All three held.
- **Run 7** re-tested nine previously-fixed items cold, in a sandbox that had never carried any of
  the fixes: the tax-year default, cash-and-equity (`portfolio-cash-still-missing`), lot-selection
  disclosure, the portfolio statement export, the settled/unsettled fee split, the repurchase-safe
  date, the tolled holding period, and both harness fixes
  (`harness-order-rejections-double-recorded`, `harness-stop-level-na-crashes-orders-cli`). All nine
  held, and the settled/unsettled split cross-checked cleanly against an independent number: a
  deliberate `insufficient_cash` rejection in the same run quoted *"$7038.00 exceeds $6972.24 of
  settled cash"* — the identical figure `final_book.settled_cash` reports. Then it found the one
  genuine regression of these three runs (#1 above).
- **Run 8** went at `/rules` and `/backtest`, surfaces the first five runs had barely touched, and
  found both remaining defects there (#2 and #3 above), plus three positives worth pinning against
  regression (folded into "Confirmed working" below).

Between the two re-test runs, **twelve previously-filed items were checked cold in fresh sandboxes
and every one held.** That is the loop closing for the third time, on top of runs 2 and 4's two
earlier closures.

### Two environment notes for future runs

- **`preview_start` hit a five-server cap** running three UAT sessions concurrently. Run 8 worked
  around it by launching its backend directly rather than through the preview tool.
- **The parent directory of the repo carries its own `.claude/launch.json`** that shadows the repo's
  own — the same quirk runs 3–5 hit with `preview_start` resolving names it should not have found. It
  now carries `uat3`–`uat8` entries, so this specific failure will not recur for those names, but the
  file lives outside git and will not travel to a fresh clone; a future run naming a new sandbox will
  hit the same shadowing.

### Still open (unchanged by this pass)

Neither of the two items already open in §R3-5 was touched by runs 6–8:

- **`wb-margin`'s negative settled cash** (a negative `settled` figure against a positive balance) —
  still a decision to be made, not a bug to fix blind.
- **A settlement-date-correct market feed, or an explicit as-of control** — still the standing item
  run 2 first asked for.

Plus two new open items from this pass: the wash-sale urgency-ordering and closed-window
safe-from-date gaps run 6 could not exercise, and
`tax-disposal-gain-loss-ignores-standalone-fee-transaction`, left unfixed on purpose (both above).

### For run 9

- Re-test the three items fixed by `c5a6b97` (§R6-8 above): the shared drawdown card, the
  event-study placeholder, and the rule validator's arity/range check.
- Exercise what run 6 could not: a ledger with more than one open wash-sale window (urgency ordering)
  and a window that genuinely closes during the replay (the closed-window safe-from date, on data
  rather than a unit test).
- Go after what is still open: `wb-margin`, the settlement-date-correct feed / as-of control, and one
  cycle against real multi-broker exports rather than the sandbox's clean one — unrun since run 2
  first asked for it.

*(Superseded in practice — see the note at the top of this file and §R9-11 below. Runs 9–11 went at
the new Institutions tab instead; the `c5a6b97` re-test above was picked up cold by run 11, and held.
The wash-sale urgency-ordering and closed-window items, `wb-margin`, and the settlement-date-correct
feed are all still open — carried forward to §R9-11's own "for run 12" pointer rather than repeated
here.)*

---

## §R9-11 — runs 9–11 (`2026-06-01`, `2026-06-15`, `2026-06-29`)

Three more persona runs, executed 2026-08-18 against isolated sandboxes (`uat/sandbox/run9`/`run10`/
`run11`) — the default sandbox ledger's mtime (2026-08-14) is unchanged by any of the three runs'
activity, confirmed directly. **30 findings, 26 distinct `finding_id`s (four ids independently hit by
two runs, which is how the recurrence below was detected), 27 confirmed, 2 partly-confirmed, 1
works-as-designed, 0 not-reproduced, 0 unverified.** Full narrative in
`docs/reports/uat-runs-9-11.md`; this is the id-level record.

| Run | Window | Sessions | Fills | Rejections | Ending equity | vs SPY |
|---|---|---|---|---|---|---|
| 9 | 2026-06-01 → 06-05 | 5 | 3 (2 buy, 1 sell) | 0 | $9,877.34 (−1.23%) | +1.54% |
| 10 | 2026-06-15 → 06-18 | 4 | 7 (6 buy, 1 sell) | 0 | $9,981.71 (−0.18%) | +0.89% |
| 11 | 2026-06-29 → 07-02 | 4 | 3 (2 buy, 1 sell) | 0 | $9,966.20 (−0.34%) | −0.85% |

Runs 10 and 11 each ran **four sessions, not five** — 2026-06-19 is Juneteenth and 2026-07-03 is the
day NYSE observed July 4th (the 4th falls on a Saturday in 2026), and `SessionCalendar` derives
sessions from stored benchmark bars by design; there is no bar on either date. Run 11's own session-4
journal states this directly. Not a defect.

These runs were the first persona exposure to the **Institutions** tab (SEC EDGAR 13F-HR and
NPORT-P filings, shipped in `d796b08`), which is why almost every finding below is scoped to it.

### One parser branch, two production risks — fixed, filed under two ids

`institutions-unidentified-position-renders-as-literal-na-lei-na` (runs 9 and 10, minor) and
`institutions-derivative-row-lei-na-literal-not-excluded` (run 11, major) are the same root cause,
independently discovered. **Verdict: confirmed, and worse than either run reported.**
**Source:** `backend/app/institutions/parse.py:_resolve_nport_key` (before the fix, lines 335–361).

`_resolve_nport_key` tested the `"N/A"` sentinel on the CUSIP fallback only; the ISIN and LEI
branches checked for emptiness alone. NPORT-P's own convention for "not applicable" is the literal
text `N/A`, and QQQ's CME E-Mini NASDAQ 100 future has `<name>`, `<lei>` and `<cusip>` all equal to
that string — so the row keyed on `LEI:N/A`, rendered with issuer `"N/A"`, and carried
**-$12,012,436.80 badged NEW**, styled identically to a real equity purchase. ARK's OpenAI position
hit the same branch at $177,028,452.35; run 11 independently found a third instance on IVV at
-$31,614,921.95. Reproduced live against the running backend (`GET /api/institutions/QQQ/changes`)
both before and after the fix in this pass.

The collision mattered more than the display: `LEI:N/A` is a key any number of unidentifiable rows
can share, so two such rows in one filing would be summed into a single fabricated position no
filing ever reported. The rows were not actually anonymous in the filing — `<title>CME E-Mini NASDAQ
100 Index Future</title>` and `<identifiers><ticker value="NQM6"/></identifiers>` are both populated
on the same element — only in the fields the parser consulted.

**What shipped** (present in the working tree, not yet committed — see below): the sentinel is
tested at every step; `<ticker>` is tried ahead of the LEI (an LEI names the counterparty, not the
instrument); `<title>` supplies the issuer name when `<name>` is a sentinel; a per-row ordinal
(`ROW:<n>`) is the terminal fallback and cannot collide by construction. Verified live: the row now
resolves to `TICKER:NQM6` / `CME E-Mini NASDAQ 100 Index Future`.

### Four more fixes

- **`institutions-counts-and-provenance-ignore-active-filters`** (run 11, major, confirmed). The
  counts strip and the holdings-total provenance line rendered the server's unfiltered tally directly
  above a table driven by the filtered rows; with a filter hiding everything, the strip kept reading
  NEW 566 / TRIM 1489 over "No rows match the current filters." Fixed: each tile now shows `shown of
  total` with a hidden-count line, keyed on rows actually being hidden rather than on a checkbox
  being ticked (the first version of the fix regressed on QQQ, which has zero `hold` rows and so
  nothing to hide, by announcing "95 of 95" — a qualifier that fires when nothing is hidden trains a
  reader to ignore it where it matters).
- **`institutions-no-absence-of-badge-caveat`** (runs 9 and 10 independently, both major, confirmed).
  The "you own this" badge needs a CUSIP match; only `robinhood.py` supplies one, `sofi.py` and
  `webull.py` both hard-code `cusip=None` (confirmed by reading both files). Against a real ledger,
  only some instruments carry a CUSIP. Apple is Berkshire's largest disclosed position (22.04%
  measured live, close to the 22.03% the personas measured), and an AAPL holding would be one of
  the uncovered instruments, so it renders unflagged — the "only holdings I also own" filter hid a
  position the user does own. Fixed: a caveat beside both ownership filters naming what an unflagged
  row does and does not mean.
- **`institutions-changes-pct-column-not-sortable`** (run 11, minor, confirmed). `Shares % chg` was
  the one numeric column with no `<SortHeader>`. Fixed, with `null` (a brand-new position has no
  prior share count to divide by) sorting to the end in both directions rather than as zero.
- **`institutions-weight-column-unlabeled-vs-portfolio-weight-of-invested`** (run 10, minor,
  confirmed). `/portfolio` labels its weight column's denominator; Institutions' bare "Weight" /
  "Weight now" headers did not, even though a 13F weight, an NPORT weight and `/portfolio`'s weight
  are three different denominators. Fixed: header reads "Weight in filing" with the denominator named
  in a `title` attribute. `docs/DEFINITIONS.md`'s matching `Weight` / `Weight Δ` entry was already
  correct and needed no change.

**All five fixes are in the working tree but not yet committed** — `git status` shows
`backend/app/institutions/parse.py`, `frontend/src/pages/Institutions.tsx` and their tests as
unstaged modifications against `d796b08`. `tests/test_definitions.py` still passes (see the gate at
the end of `docs/reports/uat-runs-9-11.md`).

### Left open on purpose

- **`institutions-live-fetch-has-no-session-lookahead-boundary`** and
  **`macro-snapshot-live-fetch-has-no-session-lookahead-boundary`** (both run 9, major, confirmed).
  Both correct in production, both a hole in the harness's no-lookahead guarantee, which covers only
  the bar store. The macro one is pre-existing, unrelated to this feature, and the more serious of
  the two — "check the macro page" is step 1 of this persona's process every session. Neither fixed;
  gating a live research surface for the harness's benefit was judged the wrong trade.
- **`institutions-cusip-bridge-never-populates-in-uat-sandbox`** (runs 9 and 10, both major,
  confirmed). A coverage gap, not a defect: the harness deliberately never mints a CUSIP. No persona
  run can ever populate `instrument.cusip` via the standard fills→close→ingest path, so the ownership
  badge can never receive live UAT signal — established instead against a real ledger, where GOOG
  and GOOGL resolve to distinct tickers off distinct CUSIPs. Run 10 filed this with
  `blocked_decision: true`: its assigned task (follow a flagged name from `/institutions` to
  `/portfolio`/`/ticker`/`/tax`) was structurally impossible for this reason.
- **`thesis-holdout-ledger-race-database-locked-500`** (run 11, minor, partly-confirmed). Mechanism
  confirmed and pre-existing: `backend/app/db/sqlite.py`'s `connect()` sets no `timeout` and no
  `busy_timeout`, and WAL still serialises two writers. Occurrence not reproduced under verification —
  the thesis holdout writes permanently, and re-running it to chase a race was judged not worth the
  cost. Left open at the reported severity.
- **`institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`** (run 10, minor,
  confirmed). No way to ask "which tracked filers hold NVDA" from `/institutions`, and no link into
  it from `/ticker` or `/portfolio`. The largest follow-on feature these three runs surfaced; recorded
  rather than built.
- **`institutions-hide-hold-default-suppresses-value-only-moves`** (run 9, minor, partly-confirmed).
  "Hide unchanged (hold) positions" defaults on, hiding the exact row (Chevron, a $3.47bn value move
  on a zero share delta) the share-vs-value split exists to surface. Only partly addressed: the
  filter now announces how many positions it hides (the fix above covers this), but the default
  itself is unchanged — a 13F like Renaissance's carries thousands of `hold` rows, and leading with
  them would bury every actual decision. Left as a judgement call, filed as-is.

### Nine new positives

Re-derived independently here, not carried from the persona's own claim:

- **Chevron/Berkshire renders the share-vs-value split correctly once unhidden** (run 9):
  `action=hold` on a zero share delta beside a -$3,471,222,716 value change.
- **The median-share-change note is accurate and stays honest about causation** (run 9): QQQ's 99
  traded positions at a median of -6.0652%, Berkshire's 13 spanning -58.04% to +658.35%, SCHD's 76 at
  -22.64% — all reproduced live — and the note never calls SCHD's figure an outflow, correctly, since
  an index reconstitution produces an identical signature.
- **Institutions API error states name valid alternatives** (run 9, reconfirmed by run 11): unknown
  key and out-of-window `?period=` both 404 naming what would have worked. The documented 409
  (`InsufficientHistory`) is currently unreachable — every catalog fund carries 2+ filing periods —
  see "for run 12" below.
- **Money and percentage figures match the raw decimal-string API to the cent** (runs 9 and 10
  independently).
- **GOOG and GOOGL are kept as distinct rows everywhere** (run 10), never merged under the shared
  issuer name.
- **A same-session wash sale reconciles exactly across `/tax`, `/wash-sales` and `/portfolio`**
  (run 10): a deliberately engineered 4-AAPL sell-and-repurchase produced an identical $6.08 figure
  on all three.
- **Sorting handles negative and near-zero decimal values correctly** (run 11), including the
  derivative row's negative value and weight, via `compareDecimalStrings`, never `parseFloat`.
- **The page scales to thousands of rows without stalling or truncating** (run 11): Renaissance's
  3,779-row Changes table and IVV's $721bn/506-holding Full Holdings both render completely.
- **A malformed `?period=` and an unknown fund key both name what would have worked** (run 11,
  reconfirming run 9 on a second fund and input).

### Environment notes for future runs

- **`preview_start` reads `.claude/launch.json` from one directory above the repo root**, shadowing
  the repo's own copy — reported by the agents driving the runs, not independently reproduced by
  launching a server here, but the shadowing file itself was inspected: the parent directory's
  `launch.json` already carries `uat9`/`uat10`/`uat11` entries alongside the repo's own copy, the same
  pattern runs 3–5 and 6–8 hit.
  This file lives outside git and will not travel to a fresh clone.
- **A five-server-per-worktree cap**, reported by the agents driving the runs, not independently
  reproduced here — the same condition already recorded above in §R6-8 ("`preview_start` hit a
  five-server cap running three UAT sessions concurrently"); cross-referenced rather than duplicated.
- **A scratchpad file consumed by one run was overwritten by a concurrent run** (run 9). An
  orchestration fault — a shared scratchpad path with no per-run subdirectory — not a repository
  defect. Lesson for the next parallel batch: give each concurrent run its own scratchpad
  subdirectory.

### For run 12

- The documented 409 `InsufficientHistory` branch is currently unreachable organically — every
  catalog fund in `backend/app/institutions/catalog.py` carries 2+ filing periods within the service's
  6-filing window.
- A multi-window wash-sale scenario — more than one open window at once, or a genuinely overlapping
  pair — is still untested by any persona through run 11.
- `wb-margin`'s negative settled cash and a settlement-date-correct market feed / explicit as-of
  control are both still the standing items run 2 first asked for.
- One cycle against real multi-broker exports rather than a sandbox's clean one, unrun since run 2.
- If `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio` gets built before run 12,
  give it the first persona pass.

---

## Confirmed working — do not regress

These were validated by independent arithmetic, not by the application agreeing with itself. They are
the strongest results of the run and belong in the regression set.

- **Realised gain, to the cent.** The persona computed a reportable loss of **−$2.88** from its own
  fill records; the application reported **−$2.88**. Proceeds and cost basis matched exactly.
- **Wash-sale handling.** 10 of 18 disposed shares had a replacement purchase inside the window.
  $3.60 of the $6.48 loss was disallowed pro rata, rolled into the replacement lot's basis, and the
  holding period tolled — with `replacement_txn_ids`, `replacement_lot_ids`, `basis_added_to_lot_id`
  and `holding_period_tolled_to` all exposed. Textbook, and the persona said so.
- **Short-term classification.** A 3-day hold classified short-term, Form 8949 Box A.
- **Ingest idempotency.** Re-importing all four session exports inserted 0 rows, recorded 0 conflicts
  and left the ledger fingerprint unmoved.
- **Partial-pricing honesty.** The portfolio page names excluded symbols at the point the total is
  displayed rather than in a footnote — precisely the behaviour the persona's spec demanded.
- **Macro page.** Used for the regime read in every session and credited as a genuine time-saver over
  tabbing between four sources.
- **Market API.** Stayed usable throughout, including in the sessions where the persona's own browser
  automation was failing it. That is why the run stayed productive.
- **Full wash-sale disallowance, twice more.** Run 3: $19.86 loss, 100% disallowed, code `W`,
  reportable $0.00. Run 4: $26.25 loss, 100% disallowed, rolled into replacement basis
  ($1,123.01 + $26.25 = $1,149.26), tolled holding period carried, cross-checked across four
  surfaces. Both against the persona's own fill records.
- **Mandate enforcement under a deliberate breach.** Run 5's 7 rejections spanned 5 different rules
  in one week, each message specific and quantified; the one genuine (non-manufactured) rejection —
  `max_single_name_weight` blocking a real trend-following add — held at the boundary and let the
  same add through the next session once resized. First persona exercise of this path in four prior
  runs.
- **Ingest idempotency, three more times.** Runs 3, 4 and 5 each re-ran their own session exports
  through `app.ingest` with 0 rows inserted and the ledger fingerprint unmoved after every replay.
- **Honest staleness labelling under a much larger gap.** Runs 3–5 replayed July against an August
  bar store — a 3–5 week pricing gap, not the 1–2 days runs 1–2 saw — and all three personas checked
  the as-of labelling and found it accurate. None filed a staleness defect.
- **Wash-sale figures reconcile to the cent across five surfaces.** Run 6, the first persona to reach
  `/wash-sales`: the tab's tile, its expanded symbol card, the Tax page's tile, Form 8949 code `W`,
  and the portfolio's own cost basis all agreed on the same $1.40, none requiring the reader to leave
  the page to derive it.
- **A `$0.00`-disallowed open-window row reads as a live warning, not an empty one.** Run 6: before a
  deliberate repurchase, the pre-trigger QQQ row on `/wash-sales` stated in full words that a
  repurchase right now would create a wash sale, rather than a bare zero that would read as
  nothing-to-see.
- **Settled/unsettled cash split cross-checked against an independent figure.** Run 7: a deliberate
  `insufficient_cash` rejection quoted "$7038.00 exceeds $6972.24 of settled cash" — the identical
  number `final_book.settled_cash` reports for the same session.
- **Portfolio's three views reconcile to the cent, checked twice.** Run 8, sessions 3 and 5: by
  instrument, by account and by tax treatment all agree, including a retirement bucket correctly
  showing zero accounts rather than being omitted or erroring.
- **Scan states its own multiple-testing correction up front.** Run 8: Benjamini-Hochberg over the
  full 18-trial set (6 expressions × 3 horizons), trials/discoveries/target FDR named before the
  table, 0 of 18 surviving correction on SPY stated plainly rather than left for the reader to notice.
- **Reverse conditioning quantifies its own overstatement.** Run 8: labelled explicitly as
  exploratory ("nothing here is a finding") and states the autocorrelation overstatement itself — 843
  bars but only 124 distinct episodes, roughly 6.8× — rather than presenting the raw sample size as
  independent evidence.
- **The Thesis loop protects its holdout.** Run 8: 5 of a 12-iteration budget spent, holdout never
  touched, a null result reported as "information about the catalog and not about the ticker" rather
  than dressed up as a finding.
- **Ingest idempotency, three more times.** Runs 6, 7 and 8 each re-ran their own session exports
  through `app.ingest` with 0 rows inserted and the ledger fingerprint unmoved after every replay.
- **Institutions: the share-vs-value split renders correctly on the flagship case.** Run 9: Berkshire's
  Chevron position shows `action=hold` on a zero share delta beside a -$3,471,222,716 value change,
  the exact case the design exists to get right.
- **Institutions: the median-share-change note is accurate and honest about what it cannot tell.**
  Run 9, reproduced live here: QQQ's 99 traded positions at a median of -6.0652%, Berkshire's 13
  spanning -58.04% to +658.35%, SCHD's 76 at -22.64% — and the note never asserts SCHD's figure is an
  outflow rather than an index reconstitution, correctly, since the two look identical in this data.
- **Institutions API error states name valid alternatives, not generic failures.** Runs 9 and 11: an
  unknown fund key 404s listing all eleven valid keys; an out-of-window `?period=` 404s naming the
  periods actually available.
- **Institutions money and percentage figures match the raw decimal-string API to the cent.** Runs 9
  and 10 independently, including a $406,974,215,192.09 fund total and a -58.04% share change.
- **GOOG and GOOGL are kept as distinct rows everywhere on Institutions.** Run 10: CUSIP 02079K107
  (GOOG) and 02079K305 (GOOGL) never merge under the shared issuer name "Alphabet Inc."
- **A same-session wash sale reconciles exactly across three pages.** Run 10: a deliberately
  engineered 4-AAPL sell-at-a-loss-then-repurchase produced an identical $6.08 deferred figure on
  `/tax`, `/wash-sales`, and as the add-back to the replacement lot's cost basis on `/portfolio`.
- **Institutions sorting handles negative and near-zero decimal values correctly.** Run 11: the
  derivative row's -$12,012,436.80 value and -0.00003228...% weight both sort into their true numeric
  position via `compareDecimalStrings`, never `parseFloat`.
- **Institutions scales to thousands of rows without stalling or truncating.** Run 11: Renaissance
  Technologies' 3,779-row Changes table and IVV's $721bn/506-holding Full Holdings both render
  completely, with the DOM row count matching the reported total exactly.
- **A malformed `?period=` and an unknown fund key both name what would have worked, on a second
  fund.** Run 11, reconfirming run 9's finding.

---

## Not defects

Kept on the record so a later run does not re-file them.

- **Ticker search / thesis buttons "broken"** (4 findings, 3 sessions, filed as blockers) —
  **not reproduced, and re-tested clean a second time.** Driving the same controls with real DOM
  events works: clicking the SPY example button navigates to `/ticker/SPY`; setting the input through
  the native value setter with an `input` event and submitting navigates to `/ticker/XLF`;
  `/thesis/NVDA` renders in full. The handler chain in `Ticker.tsx` is intact and the routes are
  registered. This was the harness's synthetic events not reaching React, not the application. **Fix
  the harness, not the app** — see below. Run 4 drove `/thesis/SPY`'s "Run thesis loop" button with a
  real `.click()` and got five real trials with q-values and a holdout summary, not a dead control —
  `thesis-page-buttons-dont-load` has now failed to reproduce twice.
- **Prices dated after the session** (2 findings, one filed blocker) — **works as designed.** The
  portfolio endpoint prices from the last stored daily close by design. The store holds bars through
  2026-08-11 while the run replays 08-03→08-07, so marks legitimately post-date the session. The
  application has no as-of parameter to price against and so cannot be wrong about one. Harness
  caveat, recorded in `uat/README.md`. Runs 3–5 saw the same design under a much larger gap (July
  replay against an August store, 3–5 weeks) and still filed nothing — see §R3-5.
- **Tax page missing trades** — **not reproduced.** Raised in session 2, when the persona had
  disposed of nothing. A gains report with no disposals is correct. Session 4's disposal appeared
  correctly.
- **Stop levels absent from the portfolio** — **works as designed.** Stops are a harness concept
  recorded on the order; they were never sent to the application, which has no order model. A feature
  request, not a defect.
- **Institutions tab reads as honest history but never enters the week's sizing decisions** (run 10)
  — **works as designed.** The tab's own copy is explicit that it shows filing history, not live
  positions (filings dated weeks to months after the replayed week), and the persona correctly never
  let a filing drive an order. For a swing trader on a one-to-several-week horizon, that is the
  intended shape for a surface whose freshest datum is 45+ days stale; a longer-horizon persona is
  the profile this page's cadence would actually match a decision cadence for.

---

## Actions on the harness itself

The run diagnosed the harness as well as the product.

**All three applied 2026-08-14** — see the "Before you file anything" section added to
`uat/personas/pro-investor-01.md`. They were recorded here on 2026-08-12 and were still unapplied
two days and four commits later, which is its own small lesson: a diagnosis written into a backlog
is not a fix, and the next run would have reproduced all five false findings.

1. **Synthetic clicks do not reach React handlers.** Cost four false findings and three sessions of a
   phantom blocker. The persona prompt should instruct: when a control appears unresponsive, retry
   via a real DOM `.click()` or a native-setter `input` event **before** filing, and navigate
   directly to the route as a cross-check.
2. **The persona cannot distinguish "absent" from "elsewhere".** It filed `rules-page-missing`
   because a URL guess redirected silently. Give future personas the route list from `App.tsx` in
   their brief, so a missing *page* is distinguishable from a missing *feature*.
3. **Duplicate ids across sessions.** The cash gap was filed five times under five ids. The
   already-used list in the prompt works but does not scale; the next run should hand the persona the
   open backlog and ask it to confirm or contradict existing items rather than re-file them.
4. **A persona should never fill in its own `verification` field.** Run 7's persona did, on all ten
   of its findings, marking itself `confirmed` throughout. `feedback.schema.json` documents the field
   as filled in by the synthesis pass specifically because a persona's own claim is not verification
   — this run produced the exact self-certification the schema note exists to prevent, even though
   every one of the ten happened to check out under independent re-derivation. The persona brief
   should state plainly that `verification` is not the persona's to set.

---

## §R12 — run 12 (`2026-05-18`), the pass that re-tested the fixes

Runs 9–11 found five defects. All five were fixed **after** those runs finished, so no persona had
ever seen the fixes. Run 12 exists to close that gap: re-test each one cold, from the outside, and
go after the two branches nobody had reached.

5 sessions, 3 fills, 0 rejections, ended $10,083.43 (+0.83%) against SPY's +0.95%. Ledger
idempotency reconfirmed — replaying both session exports inserted 0 rows and left the fingerprint
unchanged.

**Four of five held.**

| Finding | Verdict | Evidence the run produced |
|---|---|---|
| `institutions-derivative-row-lei-na-literal-not-excluded` (and its `…-unidentified-position-…` twin) | held | QQQ → `TICKER:NQM6` / "CME E-Mini NASDAQ 100 Index Future"; IVV, which has no ticker, → `ROW:247` / "S&P 500 E-Mini Index" at −$31,614,921.95; ARKK → `NAME:OPENAI GROUP PBC SERIES C`. It also checked the property that made this more than cosmetic, which no earlier run had: identifier keys are unique within every snapshot — QQQ 102/104, IVV 506/513, ARKK 46/51, zero duplicates. |
| `institutions-counts-and-provenance-ignore-active-filters` | held | RENTECH: "Filters are hiding 6 of 3779 positions; 3773 shown". IVV forced to zero rows in each section reported its own count independently. And the inverse — QQQ has no `hold` rows, so the default filter hides nothing and the tiles render unqualified. |
| `institutions-no-absence-of-badge-caveat` | held | Caveat renders beneath both ownership filters, every fund checked. |
| `institutions-changes-pct-column-not-sortable` | held | Sorts both ways; the three `null`/NEW rows stay together at the end in both directions rather than sorting as 0%. |
| `institutions-weight-column-unlabeled-vs-portfolio-weight-of-invested` | **partly** | See below. |

**The one that did not hold is the recurring shape, again.** "Weight in filing" plus a title naming
the denominator reached the Changes table. Full holdings — same page, same fund, one section
down — kept a bare "Weight", and its `HoldingSortHeader` did not even accept a `title` prop. A
reader who opened Full holdings first met the original ambiguity completely untouched.

That is now the fourth time a fix in this project has landed on one surface and not its twin: the
drawdown card (`/backtest` vs `/report`), the rule-editor placeholder (`RuleEditor` vs
`EventStudy`), the rule validator, and this. Fixed after this run and pinned by a test that asserts
**both** headers carry the label and the denominator — and that the 13F wording ("US-listed
equities only") is distinguished from the NPORT wording. Verified red with the twin reverted, green
with it restored. The pin covering both surfaces rather than only the one that broke is the whole
point.

**The two branches**

- `409 InsufficientHistory` — **still unreachable, and correctly reported as such rather than
  faked.** `/changes` takes no query parameters, so a caller cannot narrow the fixed candidate
  window the way `?period=` narrows `/holdings`, and all eleven catalog funds have two or more
  filing periods. The 409 is unit-tested; what stays untested is the *page's* rendering of it, and
  it will stay that way until the catalog holds a fund with a single filing. The 404
  `PeriodNotFound` side is genuinely distinct and reachable (`?period=1990-01-01`), which the run
  confirmed.
- **Multi-window wash sale** — carried forward a fourth time, and again not manufactured. No
  position traded into a loss during the week; forcing a sale to produce the scenario would have
  taken the persona out of character and made the data worth less than not having it. Still the
  most valuable untested path in the tax engine. It needs a run whose week actually contains a
  drawdown, which is a scheduling problem rather than a testing one.

**Positive worth keeping:** the previous commit touched `styles.css` and `parse.py`, and
`styles.css` is shared by every page. The run walked the other pages and found nothing broken.
Shared-file edits are exactly where this project has regressed before.

**Environment note.** `preview_start` reads the `.claude/launch.json` one directory **above** the
repo root. The `uat12-*` entries added there had been copied from the repo's own copy with its
unprefixed relative paths (`.venv/Scripts/python.exe`), which cannot resolve from that file's
working directory — unlike the `uat9`/`uat11` entries, which carry an `Investing dashboard/` prefix.
The run fell back to launching both processes directly. Repaired afterwards for `uat10` and `uat12`
by mirroring the `uat9` form; worth checking before the next parallel batch rather than during one.

**For run 13**

- A week containing an actual drawdown, so the multi-window wash-sale scenario is reachable in
  character.
- ~~The macro lookahead gap (`macro-snapshot-live-fetch-has-no-session-lookahead-boundary`)~~ —
  **superseded two sections below.** It was open when this note was written and is closed in
  §Fixes after run 12. Left struck rather than deleted: a run-13 brief that still named it as open
  would send a run to re-test something already fixed.
- ~~`institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`~~ — **the backend half is
  now built.** `GET /api/institutions/holders/{symbol}` answers "which tracked filers hold NVDA"
  across the whole catalog; see §Reverse holder lookup at the end of this file. The reverse *links*
  from `/ticker` and `/portfolio` into `/institutions` are still unbuilt.

---

## §Fixes after run 12 — four of the deliberately-open items closed

Runs 9–12 left a set of items open on purpose, each with recorded reasoning. Four of them are now
fixed. The reasoning for leaving them open was about scope, not about whether they were real.

| Finding | What changed |
|---|---|
| `thesis-holdout-ledger-race-database-locked-500` | `sqlite.connect` took stdlib's 5-second default lock wait and installed no busy handler, so a second writer raised `database is locked` instead of waiting. Now 15s, from one constant. The failure this prevents is not a slow query — it is a *transient* condition surfaced as a 500 for a write that would have succeeded a moment later. Covered by `tests/test_ledger_locking.py`, including a control with `timeout=0` proving the other tests exercise a real lock rather than passing vacuously. |
| `institutions-live-fetch-has-no-session-lookahead-boundary` | `/{key}/holdings` and `/{key}/changes` accept an optional `as_of`, filtering candidates on **filing date** — the date a filing became public, not the period it describes. Verified live at the boundary: `as_of=2026-08-14` returns Berkshire's Q2 (filed that day), `as_of=2026-08-13` falls back to Q1. The candidate window widens when a bound is active, since discarding the newest filings can otherwise leave too few to compare. |
| `macro-snapshot-live-fetch-has-no-session-lookahead-boundary` | Same shape, and the more serious of the two — "check the macro page" is step 1 of the persona's process every session. Series are truncated at the bound and every derived figure (latest, day/week/month/YTD change, sparkline) is recomputed from truncated data rather than relabelled. `generated_at` becomes the bound instead of wall-clock `now()`. Fear & Greed is **withheld** rather than passed through, because CNN publishes a point-in-time reading with no history to truncate and serving today's under an as-of date would be the exact lookahead this closes. |
| `institutions-derivative-row-lei-na-…` (display half) | A genuinely non-zero weight truncating to `-0.00%` now renders as an explicit bound: `<0.01%` / `>-0.01%`. QQQ's CME future, at −0.0032% of the fund, previously read as a signed zero. |

**Two things worth recording rather than burying.**

The as-of bounds exist and are tested; **they are not yet wired into the UAT harness**. A persona run still sees live filings and live macro. Closing that properly means the harness passing its session date on every request, which is a change to the harness rather than to the application, and is the obvious next step for whoever picks this up.

A correction to the first version of the locking fix: its docstring claimed `sqlite3.connect(timeout=…)` and `PRAGMA busy_timeout` were two independent mechanisms that both had to be set. They are the same knob — CPython implements the `timeout` argument by calling `sqlite3_busy_timeout`. Checked rather than argued: a `mode=ro` connection, which never runs the pragma, still reports `busy_timeout` as 15000. Both are kept, for readability, but the text now says why rather than asserting a mechanism that does not exist.

**Still open, unchanged:** `institutions-cusip-bridge-never-populates-in-uat-sandbox` (a deliberate harness property), `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio` (a feature, not a fix), `institutions-hide-hold-default-suppresses-value-only-moves` (partly addressed), `institutions-insufficient-history-409-unreachable-via-public-api` (a limit of the catalog), and the multi-window wash-sale scenario (needs a week containing a drawdown).

---

## The loop

```
persona run  ->  feedback.jsonl  ->  verify (read the source)  ->  BACKLOG.md  ->  fix
     ^                                                                              |
     +---------------- next run re-tests confirmed items --------------------------+
```

`finding_id` is the dedupe key across runs, which is why it must name the problem rather than the
session. A confirmed item that reappears in a later run under the same id is a regression; one that
does not reappear is a candidate for closing — and the next run should be pointed at this file to
check exactly that.

---

## §Reverse holder lookup — `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`, backend half

Filed by run 10 (minor, confirmed), repeated in the run-13 brief as *"the largest unbuilt thing these
runs surfaced"*. Every institutions surface answered the question fund-first — pick a filer, see its
book. There was no way to ask the other one.

**Built:** `GET /api/institutions/holders/{symbol}`, over `app.institutions.holders.find_holders`.
Walks every filer in the catalog, one EDGAR fetch each behind the existing six-hour cache, and
reports which of them disclose the symbol. Verified live: **NVDA returns 12 holders across 22 of 22
filers checked**, led by VTI ($127.8bn, 6.40% of book) and VOO ($107.7bn, 7.57%). Cold ~47s, warm ~7s.

**Two design points that are the whole value of it.**

*An empty answer is not one answer.* The lookup can fail per-filer. If three time out and the result
is an empty list, "no tracked filer holds NVDA" is false — it means "none of the nineteen I could
read". So every unreadable filer is named with its reason in `unchecked`, and `checked`/`total`
travel with the result. A reverse lookup whose failure mode is a *confident empty list* is worse than
one that is slow.

*It can only answer for symbols the user has traded.* CUSIP is the only bridge between a 13F and a
ticker, and it comes from the user's own ledger (`catalog.ledger_cusip_tickers`). **AAPL can return zero
holders** against a ledger that lacks it while VTI, VOO and IVV all certainly hold it. `symbol_resolved: false`
says so explicitly, so the empty list reads as "could not look" rather than "nobody holds it".

**Two defects found in this work by calling it for real, after unit tests passed.** The first version
called `service.load_latest(client, fund, ...)` — arguments reversed — and closed a client that has
no `close()`. Eleven tests passed against both, because the stub encoded the interface I assumed
rather than the one that exists. The stub is now bare, so any attribute the production path needs
fails loudly in tests too.

**And one piece of dead code removed for the same reason.** A ticker-matching fallback looked like it
covered the unresolvable-symbol case. It cannot: `load_latest` resolves `Holding.ticker` through
`catalog.apply_tickers` from the *same* mapping the CUSIP lookup inverts, so a holding carries a
ticker exactly when its CUSIP is already matched. Unreachable in every production path, and worse
than absent because it implied a capability that does not exist.

**Still open:** the reverse *links* — a way into this from `/ticker` and `/portfolio`, and a search
box on `/institutions`. The endpoint exists; nothing in the UI calls it yet.

---

## §R13 — run 13 (`2026-08-17_pro-investor-01`), 5 sessions, 9 findings

Week of 2026-08-17 to 08-21. Book: opened three positions, added two, exited one. Closed at
**$9,939.49 on $10,000, −0.61%**. `finalize` re-imported every session export and the ledger
fingerprint was unchanged — idempotency holds.

### The setup miss that shaped the run, stated first

**This run was not given its own sandbox.** `run.py init` and `harness/serve.py` both take
`--sandbox`, and runs 3 through 12 each used one. I ran neither with it, so run 13 shared the default
`uat/sandbox/` — which already held a prior week's trades. Session 1 opened the Portfolio page and
found seven positions before it had traded.

The persona handled it correctly (treating the `brief` command's book as truth all week) and the
findings about the *application* stand. But every observation of Portfolio, Activity and Tax page
*contents* is against a merged book, and that is my error, not the product's.

### `shared-ledger-contamination-corrupts-fifo-lot-and-wash-sale` — **re-characterised under verification**

**Filed** (session 4, major, `defect`, surface `data`): selling the run's only QQQ lot, `/tax` matched
the disposal against a **phantom lot** from another run, treated the real buy as a replacement
purchase, and **fabricated a $22.04 wash-sale disallowance** that propagated to Form 8949.

**The symptom is exactly as reported and was verified independently.** The mechanism is not a defect.
`build_lots` keys its FIFO queue on `account_id` plus instrument, which is **correct** for the thing
this application is: one person's ledger, into which many broker imports merge. That merge is the
feature. What produced the wrong number is that **every UAT run reuses the literal `account_id`
`"uat-taxable"`**, so two runs sharing one sandbox share one FIFO queue.

**Left unfixed on purpose, and re-labelled from `defect` to a harness-isolation issue.** Filed as
written it would send someone to change FIFO keying — which would break real tax math for the actual
use case to accommodate a test-harness collision. The fix belongs in the harness: pass `--sandbox`,
and consider per-run `account_id`s so a shared sandbox cannot silently merge two books.

**It is still the most valuable finding of the week**, because it shows what the contamination
actually costs: not a confusing display, but a *wrong computed tax result on a real disposal*, and the
first UAT session ever to sell anything found it.

### ~~`report-facts-table-as-of-column-always-empty` — confirmed, unfixed~~ — no longer reproduces as of run 14 (2026-08-25)

**Verified directly, not from the report, at the time:** `backend/app/report/builder.py` calls its
`_fact()` helper **39 times and passes `as_of` zero times.** The parameter exists and defaults to
`None`, so the column renders "—" on all 33 rows for every symbol. `FactTable.tsx` is correct; the gap
is upstream.

Worth the severity the persona gave it: this is the one table named for provenance, on the page built
to prove it, in an application whose stated discipline is that every figure carries an as-of.

**Update, run 14 (`2026-08-25_orchestrated-pass`, 2026-08-26):** re-verified directly against current
source and this no longer holds. `_fact()` is still called 39 times, but 22 of those calls now pass
`as_of` (`backend/app/report/builder.py:104,115,133,141,170,182,192,200,213,237,282,283,299,329,337,
347,358,371,395,405,445`), and every remaining `as_of=None` row carries an inline comment naming the
omission as deliberate — identity facts have no fetch timestamp available to this module
(`builder.py:90-94`), DATE-kind facts would only restate their own value (`:172-173,251`), and
rule-definition facts are parameters of the rule, not observations (`:317-319`). Live-checked on
`/report/NVDA`: the majority of rows now carry a real date. Someone shipped this in the roughly one
week between this entry being written and run 14 reading it, without updating this file. See §R14
below for the full re-derivation.

### `portfolio-unsettled-cash-lacks-settlement-date` — confirmed, unfixed

**Verified:** `backend/app/core/cash.py` filters `pending_inflows` on `t.settle_date > as_of` to build
the unsettled figure, then discards the date — `backend/app/api/portfolio.py` contains **no reference
to a settle date at all**. The number reaches the page; the date it clears does not. The persona
hand-reconstructed a settlement calendar from the Activity page on both sessions where it mattered.

Filed alongside its own positive counterpart, `activity-page-settlement-date-range-clear-and-correct`
— Activity already renders an honest trade-date → settle-date range. The logic is right; it just does
not reach the summary.

### `institutional-holders-panel-mislabels-422-as-service-unavailable` — filed and fixed same-week

Session 3 typed a 31-character ticker. Three panels on the page named the real cause; the holders
panel — shipped hours earlier in this same working session — blamed the deployment, because its error
branch had one catch-all message for every status. `describeFailure` now splits 422 / 404 / 5xx.
**Session 4 re-tested and confirmed the fix.** The loop closing inside one run is new.

### The lookahead finding, filed twice and not a third time

Sessions 1 and 2 both filed it (Macro, Ticker decision table, Paper Desk, Backtest, Report). Note for
whoever reads the §Fixes-after-run-12 table: that fix added an `as_of` **capability** to the
endpoints. The harness and frontend still do not pass it, so the persona's experience is unchanged.
The entry overstates what was closed.

### The persona's own verdict, worth keeping verbatim

> materially closer than session 1 — cash, equity, transaction history, lot disclosure and the
> statement export were the blocking gaps a week ago and none of them are gaps now. What's left is
> narrower: a tax-engine isolation assumption and one broken provenance promise on an otherwise-honest
> tool. I'd trial it with a second account before signing a real 8949 off it.

And where it adapted to the tool rather than being served by it — the frictions nobody files:
hand-computing 25%-cap headroom every session, cross-referencing Activity against Portfolio to
rebuild a settlement calendar, and **trusting the CLI's snapshot over the live dashboard by habit all
week, never because the UI said to.**

### For run 14

1. **`init --sandbox run14` and serve with the matching flag.** Non-negotiable; this run demonstrated
   the cost.
2. ~~**Fix the Facts-table as-of gap**~~ — **done**, confirmed by run 14 (§R14 below): `as_of` now
   flows through roughly two dozen of `_fact()`'s 39 call sites in `backend/app/report/builder.py`,
   with every undated remainder carrying a documented reason.
3. ~~**Carry the settlement date onto `PortfolioReport`**~~ — **done for the DERIVED path**, confirmed
   by run 14 (§R14 below): `unsettled_next_date`/`unsettled_full_date` now flow from
   `backend/app/core/cash.py`'s `_account_cash` through to the UI. What's left is that a real ledger's
   nonzero-unsettled accounts can all be DECLARED overrides in
   `data/accounts.toml`, not DERIVED, so the date structurally cannot reach them — a data-coverage
   gap now, not the code gap this pointer described.
4. A week containing an actual drawdown, still unreached: five sessions of a trend-stacked tape meant
   no stop ever fired.

---

## §R14 — run 14 (`2026-08-25_orchestrated-pass`)

One session, persona `pro-investor-01`. Four findings, synthesised 2026-08-26: one blocker that had
already been fixed by the time this pass reached it, one polish item whose predecessor entry (§R13
above) turned out to be stale and is corrected in place rather than left to mislead a future run, one
minor gap that narrowed under verification the same way several §R3-5/§R6-8 items did, and one minor
defect recorded with its uncertainty intact because the harness would not permit the restart needed to
resolve it.

### 1. ~~Paper Desk crashes to the ErrorBoundary on an unrecognized `exit_reason` and cannot recover through its own UI~~ — FIXED

**Verdict:** confirmed, blocker · **Raised:** once, session 1 · **Surface:** UI
**Source:** `frontend/src/api/paperdesk.ts:109-169`, `frontend/src/api/paperdesk.test.ts`,
`backend/app/paperdesk/models.py:104`, `backend/app/tournament/ladder.py:552`,
`backend/app/tournament/allocation.py:653`

Setting Paper Desk's inception date earlier than the default six-session window let allocation and
ladder cards reach `rebalance_trim` for the first time in front of a persona: both `ladder.py:552` and
`allocation.py:653` construct `RealisedTrade(exit_reason="rebalance_trim", ...)`, and
`RealisedTrade.exit_reason` is typed as a bare `str` (`backend/app/paperdesk/models.py:104`). The
frontend's `ExitReason` union did not contain `"rebalance_trim"`, `exitReasonLabel`'s exhaustiveness
guard threw on it, and the throw propagated out of render into the route's `ErrorBoundary`, replacing
the entire page — every book, every figure. Because the inception override is persisted server-side,
the crash recurred on every subsequent load, and the inception form and any reset control lived inside
the subtree that no longer rendered, leaving no in-UI path back to a working state.

**What shipped.** `rebalance_trim` added to the `ExitReason` union with a `"Rebalance trim"` label
(`paperdesk.ts:109-115, 160-161`). More significantly, `exitReasonLabel`'s exhaustiveness check changed
from a throwing `assertNever` call to an unused `const _exhaustive: never = reason` assignment
(`paperdesk.ts:162-168`): a union member added without a case is still a build-time error, but a value
the server sends that this build has never heard of now renders as its raw string instead of taking
the page down — the module's own docstring names this as the point: *"a closed union over
server-supplied data is a promise the client cannot keep."* Verified live afterward: 13
`rebalance_trim` trades present in the payload, page rendered normally, no ErrorBoundary.

**Tests:** `frontend/src/api/paperdesk.test.ts` (3) — every known reason labels distinctly and never
echoes the raw wire value; `rebalance_trim` specifically labels `"Rebalance trim"`; and a value cast as
`ExitReason` that the union has never seen (`"some_new_reason"`) does not throw and renders as-is —
the regression guard for exactly this failure.

### 2. `report-facts-table-as-of-column-always-empty` — run 13's verdict does not hold; corrected in place, not silently

**Verdict:** not reproduced, contradicting §R13's `confirmed, unfixed` · **Surface:** UI
**Source:** `backend/app/report/builder.py:45-461`

Run 13 (2026-08-17) reported `_fact()` called 39 times with `as_of` passed zero times, so the AS OF
column rendered `—` on all 33 rows for every symbol. Re-verified directly against current source and
this no longer holds: `_fact()` is still called 39 times, and **22 of those calls now pass `as_of`** —
`builder.py:104, 115, 133, 141, 170, 182, 192, 200, 213, 237, 282, 283, 299, 329, 337, 347, 358, 371,
395, 405, 445`. Every remaining `as_of=None` row carries an inline comment explaining the omission as
deliberate rather than an oversight:

- Identity facts (`Symbol`, `Name`, `Exchange`, `Type`, `Currency`) carry no fetch timestamp available
  to this module, unlike `Coverage.fetched_at`, which the builder never receives (`builder.py:90-94`).
- DATE-kind facts (`drawdown.peak_date`, `drawdown.trough_date`, `drawdown.current_peak_date`) would
  only restate their own value as an as-of (`builder.py:172-173, 251`).
- Rule-definition facts (`Rule with the largest edge`, `Expression`, `Horizon (bars)`) are parameters
  of the rule, not observations, and don't change with the calendar (`builder.py:317-319`).

Live-checked on `/report/NVDA`: the majority of Facts-table rows carry a real date (Sessions, Last
price, Drawdown basis/episodes, Rules evaluated/firing, Hit rate vs baseline, etc.); the remaining `—`
rows are exactly the identity/DATE/rule-definition rows named above, each with its own documented
reason. Someone shipped this fix in the roughly one week between run 13's synthesis and this pass,
without updating this file — corrected above (§R13's own entry) and in its "For run 14" pointer rather
than left for a future run to re-discover or, worse, re-attempt.

### 3. `portfolio-unsettled-cash-lacks-settlement-date` — narrowed, not closed: the code gap is fixed, only declared-override accounts still lack a date, by design

**Verdict:** partly confirmed (narrowed) · **Surface:** data
**Source:** `backend/app/core/cash.py:576-605` (`_apply_declaration`), `:665-736` (`_account_cash`),
`data/accounts.toml`, `frontend/src/pages/Portfolio.tsx:315-326, 1424-1429`

The on-screen symptom run 13 described still reproduces — the top Cash tile and the `wb-margin`/
`wb-roth` rows in Cash-by-account still show no settlement date — but the diagnosis run 13 gave
(`backend/app/api/portfolio.py` "contains no reference to a settle date at all") no longer matches the
code. `_account_cash`, the DERIVED path, now computes `unsettled_next_date`/`unsettled_full_date` from
`pending_inflows` and returns them on `AccountCash`; `Portfolio.tsx` renders them at both the aggregate
tile (`:315-326`) and the per-account tile (`:1424-1429`) via a shared `settlementClause(...)` helper,
whose own comment cites this exact backlog entry: *"this figure used to say only how much was
unsettled, never when it would stop being so"* (`Portfolio.tsx:319-320`).

What still clears both fields to `None` is `_apply_declaration` (`cash.py:576-605`), unconditionally,
for any account whose cash comes from a manual override rather than ledger derivation — with its own
comment explaining why: *"a declared balance is a single figure the user read off their broker... there
is no per-row settle_date behind a declared unsettled figure to attach a date to."* Checking
`data/accounts.toml` confirms every account in that ledger carries a `[[cash]]` override and
none is DERIVED — and only two of them (`settled = "-N.NN"`, `unsettled = "N.NN"`) carry a nonzero
unsettled figure. So the now-working DERIVED-path plumbing has no account in that real ledger where it
can ever fire.

The persona's underlying complaint — "I cannot tell when $N,NNN.NN of unsettled proceeds becomes
deployable" — still holds exactly as reported. But the fix that would close it is not §R13's "For run
14" pointer #3 ("carry the value already computed onto `PortfolioReport`") — that value is null
specifically because these two accounts are declared, not derived. The real next step is either moving
`wb-margin`/`wb-roth` onto the DERIVED path (the `accounts.toml` comments suggest that was a deliberate
accuracy override, not an oversight) or explicitly labelling a declared unsettled figure "date not
available — declared balance," the way the per-account tile's staleness note already does for
`declared_as_of`.

### 4. `overview-calendar-widget-404s-despite-registered-route` — new, minor, left unverified on purpose

**Verdict:** unverified · **Surface:** API
**Source:** `backend/app/api/calendar.py:33, 53`, `backend/app/main.py:33, 128`

On every load of `/overview`, the CALENDAR panel and a direct `fetch('/api/calendar/events?days=60')`
both returned 404 (`{"detail":"Not Found"}`), while every other endpoint exercised through the same
proxy (health, portfolio, macro, paperdesk, tax, competition, institutions) returned normal responses —
not a proxy-wide outage. Checked against current source: `calendar.py:33` defines
`router = APIRouter(prefix="/api/calendar", ...)` with a `GET /events` route at `:53`, and
`main.py:128` calls `app.include_router(calendar.router)` — so the route is registered in the
checked-out tree. (The finding cited `main.py:119`; the include call is now at `:128`, a small drift
from unrelated edits since the finding was written, not itself a discrepancy worth reporting.)

The tester was not permitted to restart the backend process, so "the running process predates this
router" could not be ruled out as the cause. Recorded as an observed discrepancy between source and
live response, not a diagnosed code defect — **do not close this as a code bug and do not close it as
a non-issue on this entry's evidence alone.** The next run should re-test against a freshly started
backend before either verdict is assigned.
