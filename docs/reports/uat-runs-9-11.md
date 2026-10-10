# UAT runs 9–11 — first exposure to Institutions, five fixes, five items left open on purpose

Three more persona runs (`2026-06-01`, `2026-06-15`, `2026-06-29`), 30 findings across 26 distinct
`finding_id`s, executed 2026-08-18 against three isolated sandboxes. Full detail and every id is in
`uat/feedback/BACKLOG.md` §R9-11; this is the narrative of what landed and why. As with every prior
batch, the verdicts below are re-derived against the source in this pass, not copied from the
personas' own claims — the `verification` block on every finding documents what was actually checked.

**Verdicts: 27 confirmed, 2 partly-confirmed, 1 works-as-designed. Zero not-reproduced, zero
unverified.**

## Why these three runs happened

Commit `d796b08` shipped a new **Institutions** tab: SEC EDGAR filings, Form 13F-HR for institutional
managers and Form NPORT-P for the real portfolios of major ETFs, with quarter-over-quarter change
detection. Runs 9–11 were the first persona exposure to it, each with a different emphasis — run 9
research surface, run 10 cross-surface reconciliation, run 11 edges and regression — and each running
concurrently against its own sandbox (`uat/sandbox/run9`/`run10`/`run11`).

| Run | Window | Sessions | Fills | Rejections | Ending equity | vs SPY |
|---|---|---|---|---|---|---|
| 9 (`2026-06-01`) | 2026-06-01 → 06-05 | 5 | 3 (2 buy, 1 sell) | 0 | $9,877.34 (−1.23%) | +1.54% |
| 10 (`2026-06-15`) | 2026-06-15 → 06-18 | 4 | 7 (6 buy, 1 sell) | 0 | $9,981.71 (−0.18%) | +0.89% |
| 11 (`2026-06-29`) | 2026-06-29 → 07-02 | 4 | 3 (2 buy, 1 sell) | 0 | $9,966.20 (−0.34%) | −0.85% |

As with every prior run, five (or four) sessions says nothing about the persona's process —
`metrics.json`'s own `$comment` repeats it on all three runs. **Runs 10 and 11 each ran four
sessions, not five, and that is correct, not a defect**: 2026-06-19 is Juneteenth and 2026-07-03 is
the day NYSE observed July 4th (the 4th itself falls on a Saturday in 2026), and `SessionCalendar`
derives its sessions from the stored benchmark bars by design — there is no bar on either date to
trade against. Run 11's own session-4 journal states this directly: *"2026-07-03 has no stored SPY
bar — NYSE observes July 4th on the preceding Friday when the 4th falls on a Saturday, as it does in
2026 — so the harness's own no-lookahead calendar correctly stopped at 07-02 rather than fabricating a
fifth session."*

All three sandboxes are isolated from the shared one and from each other — the default sandbox
ledger's mtime (`uat/sandbox/store/ledger.sqlite`, 2026-08-14) is unchanged by any of the three runs'
2026-08-18 activity, confirmed directly here.

## The headline: one parser branch, two production risks

The sharpest defect these runs found is a parser gap that reached production twice under two
different `finding_id`s, because two runs hit it independently on the same day —
`institutions-unidentified-position-renders-as-literal-na-lei-na` (runs 9 and 10) and
`institutions-derivative-row-lei-na-literal-not-excluded` (run 11), same root cause.

`_resolve_nport_key` in `backend/app/institutions/parse.py` tested the `"N/A"` sentinel on the CUSIP
fallback only. NPORT-P's own convention for "this field does not apply" is the literal text `N/A`,
and QQQ's CME E-Mini NASDAQ 100 future has `<name>`, `<lei>` and `<cusip>` **all** equal to that
string. The ISIN and LEI branches checked only for emptiness, so the row keyed on `LEI:N/A`, rendered
with issuer `"N/A"`, and carried **-$12,012,436.80 badged NEW** — the same green styling as an actual
equity purchase. ARK's OpenAI position hit the identical branch at $177,028,452.35, and run 11
independently found a third instance on IVV at -$31,614,921.95. Verified live against the running
server (`GET /api/institutions/QQQ/changes`): before the fix this returns the `N/A`/`LEI:N/A` row; the
fix applied in the working tree resolves it to `cusip: "TICKER:NQM6"`, `issuer: "CME E-Mini NASDAQ 100
Index Future"`.

The display was the smaller problem. `LEI:N/A` is a key any number of rows can share — the resolver
had no guard against two genuinely different, unidentifiable instruments in the same filing being
grouped under one key and having their values silently summed into a position no filing ever reported.
The filing was not actually silent about the row, only in the fields the parser consulted first: the
same `<invstOrSec>` element carries `<title>CME E-Mini NASDAQ 100 Index Future</title>` and
`<identifiers><ticker value="NQM6"/></identifiers>`, both populated, both ignored.

**What shipped** (uncommitted in the working tree as of this writing — see "State of the fix" below):
the sentinel (`N/A`, `NA`, `-`, empty, or all-zero) is now tested at every step of the fallback chain;
`<ticker>` is tried ahead of the LEI, because an LEI names the counterparty rather than the instrument;
`<title>` supplies the issuer name when `<name>` is a sentinel; and a per-row ordinal (`ROW:<n>`) is
the terminal fallback, which cannot collide with anything by construction. Verified live: every key in
QQQ's and IVV's current filings is now unique.

## The other four fixes

### 2. Filtered tables under an unfiltered counts strip

`institutions-counts-and-provenance-ignore-active-filters` (run 11, major). With Renaissance
Technologies selected and "Only holdings I also own" checked (dispatched via real DOM events, not the
harness's synthetic form-filler, specifically to rule out a harness artifact), the Changes table
correctly emptied to "No rows match the current filters" while the counts strip directly above it kept
reading the server's unfiltered tally — **NEW 566 / EXIT 639 / ADD 1079 / TRIM 1489 / HOLD 6**. The
same pattern reproduced on IVV's Full Holdings section: an empty filtered table under a provenance line
still reading "across 506 holdings." Confirmed by reading the render in
`frontend/src/pages/Institutions.tsx`: `<CountsStrip counts={delta.counts} />` was wired to the
server's unfiltered tally, never the `rows` array the table itself renders.

**What shipped.** Each tile now shows `shown of total` with a line naming how many positions the
active filters are hiding, and the Full Holdings table carries the same qualifier. The fix note records
a self-correction worth keeping on file: the first version keyed the qualifier on "is a checkbox
ticked" rather than "are rows actually hidden," so QQQ — which has zero `hold` rows to begin with —
read "95 of 95" beside "Filters are active: 104 of 104," a qualifier that fires when nothing is hidden
and teaches a reader to stop trusting it exactly where it matters. It now keys on the count of hidden
rows.

### 3. No caveat for a missing badge

`institutions-no-absence-of-badge-caveat` (runs 9 and 10 independently, both major). The "you own this"
badge requires a CUSIP match, and the page never said what an absent badge means. Verified directly
against a real ledger: **only some instruments carry a CUSIP** — only
`backend/app/ingest/adapters/robinhood.py` extracts one; `sofi.py` and `webull.py` both hard-code
`cusip=None` on every row (confirmed by reading both files directly), because neither export format
has the column. The concrete case run 9 and run 10 both landed on: Apple is Berkshire's largest
disclosed position — measured live at 22.04% of the book (`GET /api/institutions/BRK/holdings`, close
to the 22.03% the personas measured on 2026-08-18) — a user can hold AAPL, and AAPL can be one of the
instruments with no CUSIP (`SELECT cusip FROM instrument WHERE primary_symbol='AAPL'` returns `NULL`
against the real ledger), so it renders unflagged. The "only holdings I also own" filter therefore hid
a position the user can own while implying the hidden set was not owned.

**What shipped.** A caveat beside both ownership filters: *"Matched by CUSIP. A holding you own can
still go unflagged — only one of the three broker imports carries CUSIPs at all, so an unflagged row
means no CUSIP match, not that you do not own it."*

### 4. The one unsortable numeric column

`institutions-changes-pct-column-not-sortable` (run 11, minor). Every other numeric column in the
Changes table (`Shares Δ`, `Value Δ`, `Weight now`) was wired through `<SortHeader>`; `Shares % chg`
was a plain `<th>` with no click handler. Confirmed by reading the header row directly.

**What shipped.** Sortable like its neighbors, with the null case handled deliberately: a `NEW`
position has no prior share count to divide by, so `shares_pct_change` is `null`, and sorting nulls as
zero would file a quarter's most decisive buys among the positions that did not move. New positions now
sort together at the end of the order in both directions.

### 5. An unlabelled denominator

`institutions-weight-column-unlabeled-vs-portfolio-weight-of-invested` (run 10, minor). `/portfolio`'s
own weight column is labelled "Weight (of invested)" specifically to name its denominator; the
Institutions tables' "Weight" / "Weight now" headers carried no equivalent, even though a 13F weight
(share of a manager's US-equities-only 13(f) book) and an NPORT weight (share of an ETF's whole
disclosed portfolio) and `/portfolio`'s weight (share of the user's own priced market value) are three
different denominators under one unqualified-looking column name.

**What shipped.** The header now reads "Weight in filing" with a `title` attribute naming the
denominator explicitly — for a 13F, that it covers US-listed equities only, not the manager's whole
book or AUM. `docs/DEFINITIONS.md` already carries the matching entry (`Weight` / `Weight Δ`, citing
`institutions/parse.py` and `institutions/deltas.py`).

### State of the fix

All five fixes are present in the working tree (`backend/app/institutions/parse.py`,
`frontend/src/pages/Institutions.tsx`, plus the matching test and style updates) but **are not yet
committed** — `git status` shows them as unstaged modifications against `d796b08`, the commit that
shipped the tab. `docs/DEFINITIONS.md`'s "Weight" entry, unlike the other four fixes, was already
correct as of `d796b08` and needed no change here. `tests/test_definitions.py` still passes (see the
gate at the end of this report).

## Left open on purpose — recorded so a later run does not "fix" these blind

- **`institutions-live-fetch-has-no-session-lookahead-boundary`** (run 9, major) and
  **`macro-snapshot-live-fetch-has-no-session-lookahead-boundary`** (run 9, major). Both confirmed,
  both correct behaviour in production — a user looking at either page today should see today's data
  — and both a genuine hole in the harness's no-lookahead guarantee, which covers the bar store
  (`AsOfMarket`) and nothing else. `GET /api/institutions/BRK/holdings` against run 9's sandbox
  returned a 13F filed 2026-08-14, more than two months after the run's last session, with nothing
  gating it. The macro one is the more serious of the two and is **pre-existing, unrelated to this
  feature** — `build_snapshot` has stamped `generated_at=dt.datetime.now(dt.UTC)` with no as-of
  parameter since before this feature existed, and "check the macro page" is step 1 of this persona's
  mandated process every session, so it sits in front of every regime read. Neither is fixed; gating a
  live research surface purely for a test harness's benefit was judged the wrong trade.
- **`institutions-cusip-bridge-never-populates-in-uat-sandbox`** (runs 9 and 10, both major). A
  coverage gap, not an application defect: `uat/harness/ingest.py` deliberately never mints a CUSIP,
  correctly, because inventing security identifiers inside a provenance-first ledger is worse than
  omitting them. The consequence is structural — no persona run, ever, via the standard
  fills→close→ingest path, can populate `instrument.cusip`, so the ownership badge (the tab's headline
  capability) can never receive live signal from a UAT session. That the bridge itself works was
  established outside the harness, against the real ledger, where GOOG and GOOGL resolve to distinct
  tickers off distinct CUSIPs (see "Confirmed working" below). Run 10's persona flagged this with
  `blocked_decision: true` — its assigned task was to follow a flagged name from `/institutions` to
  `/portfolio`, `/ticker` and `/tax`, and it structurally could not, for the same reason.
- **`thesis-holdout-ledger-race-database-locked-500`** (run 11, minor, partly-confirmed). The
  mechanism is confirmed and pre-existing, unrelated to Institutions: `backend/app/db/sqlite.py`'s
  `connect()` opens with `sqlite3.connect(uri, uri=True, isolation_level=None)` — no `timeout`
  argument and no `busy_timeout` pragma, so it falls back to sqlite3's 5-second default — and WAL mode
  still serialises two writers. `/thesis/XLE` fires `GET /api/thesis/ledger` and `GET
  /api/thesis/holdout` concurrently; the backend log showed one `database is locked` 500 followed by a
  clean 200 a moment later on the same endpoint. The occurrence was **not** reproduced under
  verification — the thesis holdout writes permanently to the ledger, and re-running it to chase a
  race was judged not worth the cost. Left open at the reported severity.
- **`institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`** (run 10, minor). Confirmed
  as a genuine gap: there is no way to ask "which tracked filers hold NVDA" from `/institutions`, and
  no link into it from `/ticker/:symbol` or `/portfolio`. `grep -i institutions` across
  `frontend/src/pages` finds only `Institutions.tsx` and its test. This is the largest follow-on
  feature these three runs surfaced, not a fix to the specific defect requested, and was recorded
  rather than built.
- **`institutions-hide-hold-default-suppresses-value-only-moves`** (run 9, minor,
  partly-confirmed). The "Hide unchanged (hold) positions" filter defaults on, hiding — on first load
  of Berkshire's Changes table — exactly the row (Chevron, a $3.47bn value swing on a zero share
  delta) the page's own share-vs-value split exists to make legible. Only partly addressed: the filter
  now announces how many positions it is hiding (the fix for #2 above covers this case too), but the
  default itself is unchanged, because a 13F like Renaissance's carries thousands of `hold` rows and
  leading with them would bury every actual decision. Left as a judgement call rather than resolved
  quietly.

## Confirmed working — nine new positives

All nine are independently re-derived here, not carried from the persona's own claim, and are also
recorded in `uat/feedback/BACKLOG.md`'s "Confirmed working — do not regress" section:

- **Chevron/Berkshire renders the share-vs-value split correctly once unhidden** (run 9): `action=hold`
  on a zero share delta beside a -$3,471,222,716 value change, with the value column explicitly labelled
  "(incl. price)" — the exact case the whole design exists to get right.
- **The median-share-change note is accurate and stays honest about causation** (run 9): recomputed
  independently — QQQ 99 traded positions (add + trim) at a median of **-6.0652%**, verified live;
  Berkshire's 13 traded positions span **-58.04% to +658.35%** (Capital One and Alphabet respectively),
  verified live; SCHD's 76 traded positions (8 add + 68 trim) sit at a median of **-22.64%**, verified
  live — and the note stops short of calling SCHD's figure an outflow, correctly, since an index
  reconstitution produces an identical signature.
- **Institutions API error states name valid alternatives, not generic failures** (run 9, reconfirmed
  by run 11): an unknown fund key 404s listing all eleven valid keys; an out-of-window `?period=`
  404s naming the periods actually available. The documented 409 (`InsufficientHistory`) could not be
  organically reached by either run — every catalog fund already carries 2+ filing periods within the
  service's 6-filing window — recorded as untestable with the current catalog rather than guessed at.
- **Money and percentage figures match the raw decimal-string API to the cent** (runs 9 and 10
  independently): Capital One's -58.04% share change, Chevron's -$3,471,222,716.00 value delta, a
  $406,974,215,192.09 fund total — none rounds, none passes through a float, matching this persona's
  standing concern (fraction-vs-0-100 unit ambiguity) on a page new enough that the bug would be
  easy to miss.
- **GOOG and GOOGL are kept as distinct rows everywhere** (run 10): CUSIP 02079K107 (GOOG, Class C)
  and 02079K305 (GOOGL, Class A) never merge under the shared issuer name "Alphabet Inc.," which is
  the CUSIP-not-name design decision paying for itself on the most common instrument where it would
  otherwise fail.
- **A same-session wash sale reconciles exactly across three pages** (run 10): a deliberately
  engineered sell-at-a-loss-then-repurchase (4 AAPL, $12.16 loss, 2 shares repurchased) produced an
  identical $6.08 deferred figure on `/tax`, `/wash-sales`, and as the add-back to the replacement
  lot's cost basis on `/portfolio` — a real decision surviving contact with every surface that touches
  cost basis.
- **Sorting handles negative and near-zero decimal values correctly** (run 11): the derivative row's
  -$12,012,436.80 value delta and its -0.00003228...% weight both sort into their true numeric
  position via `compareDecimalStrings`, never through `parseFloat`.
- **The page scales to thousands of rows without stalling or truncating** (run 11): Renaissance
  Technologies' 3,779-row Changes table and IVV's $721bn, 506-holding Full Holdings table both render
  completely, sorted and filterable, with the DOM row count matching the reported total exactly.
- **A malformed `?period=` and an unknown fund key both name what would have worked** (run 11,
  reconfirming run 9's finding on a second fund and a second bad input).

## Environment notes for future runs

- **`preview_start` reads `.claude/launch.json` from one directory above the repo root**, which
  shadows the repo's own copy. Reported by the agents driving all three runs; not independently
  reproduced by launching a server here, but the shadowing file itself was found and inspected: the
  parent directory (`Investing dashboard/.claude/launch.json`, one level above this repo) already
  carries `uat9`, `uat10` and `uat11` backend/frontend entries alongside the repo's own copy of the
  same entries added under this pass's changes — the identical pattern runs 3–5 and 6–8 hit and
  worked around for their own sandbox names. That file lives outside git and will not travel to a
  fresh clone, so a future run naming a new sandbox will hit the same shadowing again.
- **A five-server-per-worktree cap.** Reported by the agents driving the runs, not independently
  reproduced here. This is the same condition already recorded in `uat/feedback/BACKLOG.md` §R6-8
  ("`preview_start` hit a five-server cap running three UAT sessions concurrently; run 8 worked around
  it by launching its backend directly") — cross-referenced here rather than logged as a new,
  separate finding.
- **A scratchpad file consumed by one run was overwritten by a concurrent run**, reported by run 9.
  This is an orchestration fault in how the three runs were briefed — a shared scratchpad path with
  no per-run subdirectory — not a repository defect. The fix belongs in the next parallel batch's
  setup: give each concurrent run its own scratchpad subdirectory.

## For run 12

- The documented 409 `InsufficientHistory` branch on `/api/institutions/{key}/...` is currently
  unreachable organically — every catalog fund in `backend/app/institutions/catalog.py` carries at
  least two filing periods within the service's 6-filing candidate window. Exercising it needs either
  a synthetic catalog entry or a fund whose filing history genuinely runs short.
- A multi-window wash-sale scenario — more than one open window at a time (urgency ordering was
  flagged as untested as far back as §R6-8) or a genuinely overlapping pair — is still untested by any
  persona through run 11.
- `wb-margin`'s negative settled cash and a settlement-date-correct market feed / explicit as-of
  control are both still the standing items run 2 first asked for.
- One cycle against real multi-broker exports rather than a sandbox's clean one, unrun since run 2.
- If `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio` (above) gets built before
  run 12, it should get its first persona pass then.

---

## Postscript: run 12 re-tested all five fixes

The five fixes above shipped *after* the runs that found them, so no persona had seen any of them.
Run 12 (`2026-05-18`, 5 sessions, +0.83% against SPY's +0.95%) re-tested each cold.

**Four held.** The parser's sentinel fix holds across QQQ, IVV and ARKK, and the run checked
something no earlier one had: identifier keys are unique within every snapshot (QQQ 102/104, IVV
506/513, ARKK 46/51, zero duplicates) — the collision the ordinal fallback exists to prevent. The
counts qualifier holds in both directions, including the inverse case where nothing is hidden. The
caveat and the sortable percentage column hold.

**One was half-done, in this project's most familiar shape.** "Weight in filing" reached the
Changes table and not Full holdings, one section down the same page. That is the fourth time a fix
here has landed on one surface and not its twin — after the drawdown card, the rule-editor
placeholder and the rule validator. It is fixed, and pinned by a test that asserts *both* headers,
verified red with the twin reverted.

Neither of the two branches nobody had reached was reached, and both were reported as unreached
rather than manufactured: the `409` is unreachable because `/changes` accepts no parameters and
every catalog fund has two or more filings, and the multi-window wash sale needs a week that
actually contains a drawdown. Full detail in `uat/feedback/BACKLOG.md` §R12.
