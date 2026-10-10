# Autopilot card on the Paper Desk — plan

*Drafted 2026-09-01. Design only; nothing below is built yet. Not investment advice.*

## 0. What the owner asked for

One more card on the Paper Desk, named **Autopilot**, seated like the reference strategy cards,
funded with **$100,000**, trading **from its own inception date**, so the owner can watch how the
Agent Workflow (regime → strategy select → screened universe → research → gate → next-open orders)
actually trades day by day. The Round 33 Phase B screened workflow is the driver — it is the thing
the `Round33-PhaseB-Daily` scheduled task feeds every weekday.

## 1. What exists today, measured 2026-09-01

| Fact | Where | Consequence for the card |
|---|---|---|
| Every workflow arm already trades a persistent paper book seeded at `STARTING_CASH = 100000` | `app/workflow/pipeline.py:103`, `app/workflow/book.py` | The $100k seat already exists; the card reads it, it does not create it. |
| Phase B books live at `data/agentdesk/workflow/book/screen/<arm>.json`; only `raw_signal` and `full_workflow` exist there | `app/workflow/book.py:104` (`book_path`), `pipeline.py:90` (`SCREENED_ARMS`) | The card's source is `(arm="full_workflow", universe_source="screen")`. |
| `screen/full_workflow.json`: adopted 2026-08-03, **0 orders, 0 fills, cash $100,000** | on disk | The card will render flat at $100,000 with "no trades since inception" on day one. That is the honest state, not a bug in the card. |
| `screen/raw_signal.json` (the null arm): 130 orders, **117 rejected**, 5 filled, 8 pending, cash $9,487 | on disk | 90% of the null arm's ledger is re-buys of names it already holds, refused on the 25% single-name cap. Rendered as-is, a rejections callout would swamp the panel. |
| Live screened runs on 2026-09-01 ended with `no entry candidates fired`; backfill runs skip research with `workflow budget exhausted (0.01 < 4.00)` by design | `data/agentdesk/workflow/runs/*` | The researched arm has never been handed a candidate. The card must show *why* it is flat (last run's outcome), or it reads as broken. |
| `snapshot_equity` has **no callers anywhere** | `grep -rn snapshot_equity backend/app` | `BookState.equity_curve` is empty on every book, forever. The card must build its own curve from the persisted fills. |
| `loop.run_once` (the in-process `workflow_autopilot` daemon) fills only the four **card-mode** books. `POST /api/workflow/book/execute` gained a `universe_source` field today (uncommitted, another session) so the page button can now reach the screen books when asked | `app/workflow/loop.py:142-205`, `app/api/workflow.py:236` | The screen books are filled by the scheduled task (`phase_b._fill_screen_books`) and, once that change lands, by the button with `universe_source="screen"`. The daemon still never touches them. |
| The workflow stages **buys only**; there is no sell path | `held_lots` docstring (`app/workflow/book.py:519`), no `"sell"` in `pipeline.py` | Whatever the Autopilot buys it holds forever. The card must say so on its face. The card's own stop / exit rules are never applied to workflow fills. |
| `Desk.kind` is a closed literal `"rules" \| "ladder" \| "allocation"` on both sides | `app/paperdesk/models.py`, `frontend/src/api/paperdesk.ts:414` | A fourth kind is additive. The frontend's only kind switch (`BookStatistics.tsx:36`) falls through to `DeskRules`, so an unknown kind degrades, it does not throw. |
| The trading book's own seat is **$60,000** (`PURPOSE_SPECS[TRADING].seed`); default inception 2026-08-15, and an override to **2026-08-27** is in effect today | `app/paperdesk/desk.py:774` (`opening_capital`), `:427` (`INCEPTION`), `data/paperdesk/inception.json` | The Autopilot seat is $100k and starts 2026-08-03. Both differ from the book it sits in; both must be stated on the panel, never blended into the book's totals. |
| The existing setting `workflow_autopilot` already means "run the daily fill daemon" | `app/config.py:331` | Reuse the word on purpose: the card shows what that autopilot trades. Do not invent a second meaning. |

## 2. Design

### 2.1 Where the card lives

- **Trading book, one extra `Desk`**, `agent_id = "autopilot-workflow"`, `kind = "autopilot"`.
- It is **not** a strategy card in `library/`: `_load_card` would try to validate it as a
  `StrategyCard`, and `app.tournament.jobs._resolve_cards` must never see it. `_book` gets one
  branch: `if agent_id == AUTOPILOT_AGENT_ID: desks.append(autopilot.build_desk(...))`.
- Seated by a setting, default on: `paperdesk_autopilot_seat: bool = True`, plus
  `paperdesk_autopilot_source: str = "screen:full_workflow"` so the owner can point the card at
  `card:full_workflow` or the null arm without a code change.
- Roster order: last in the trading book. `DEFAULT_VISIBLE_AGENT_IDS` in `PaperDesk.tsx` gains
  `"autopilot-workflow"` so it is ticked on first load (the owner asked to see it).

### 2.2 The new module: `app/paperdesk/autopilot.py`

Keep it out of `desk.py` (3,173 lines already). One public function:

```
build_desk(settings, window, *, arm, universe_source, mandate, taxable) -> Desk
```

Inputs are the persisted `BookState` (via `book_mod.load_book`) and the stored bars. Everything is
a pure function of those two, so it is cacheable and auditable the same way the rules desks are.

| `Desk` field | Source |
|---|---|
| `starting_equity` | `book.starting_cash` ($100,000) |
| `holdings` | `book.broker_state["fills"]` walked in `(trade_date, order_id)` order into FIFO lots (reuse the walk in `book.held_lots`), each marked at `window.as_of` close via `AsOfMarket`. `stop_price`/`target_price`/`sessions_to_time_stop` are `None`: the workflow applies none. |
| `cash`, `positions_value`, `equity` | `PaperBroker.from_state(mandate, book.broker_state).mark(market)` — the broker's own numbers, exactly as `api/workflow._book_view` does. `equity == cash + positions_value` to the cent. |
| `trades` | closed round trips from the fill walk (none today; the walk is there so the day a sell exists it renders). |
| `decisions` | one `Decision` per **filled** order (`action="enter"`, `reason=` the order's `regime` + gate that admitted it), price/qty from `order.fill`. |
| `signals` | one `Signal(entry_fires=True, held=False)` per **pending** order — reuses the "Upcoming signals" panel: "USO gets bought at the next open". `rank_value`/`entry_rank` `None`. |
| `rejections` | rejected orders grouped by `reject_reason` through the same grouping `_group_rejections` uses. |
| `total_return`, `excess_return` | computed in `_book` exactly as for every other desk (excess is rebased against the book's primary benchmark there already). |
| `max_drawdown`, `capital_exposure` | from an **equity curve the module builds itself**: for each session in `window.session_dates` on or after the book's inception, cash-after-fills-to-date + Σ qty × stored close. Fed to `app.backtest.metrics.compute` — the one implementation of drawdown in the codebase. A session where any held symbol is unpriced yields a `None` point, never a partial figure (same rule as `snapshot_equity`). |
| `tax` | `book_mod.tax_summary(book, settings=settings)` — already exists, already runs the real tax engine over the fills. |
| `universe` | every symbol that has ever appeared on an order in this book (the screened universe changes daily; there is no fixed list to print). |
| `entry`, `exit`, `position_pct`, `rank_by`, `ladder` | `None`. `max_positions` from the mandate. |
| `autopilot` (new optional block, mirrors `ladder`) | `arm`, `universe_source`, `current_card_id`, `card_adopted_date` (the seat's own inception), selector id and screen entry rule from `phase_b`, `pending_orders`, `last_run` (`run_id`, `state`, `created_at`, one-line outcome such as "no entry candidates fired"), `research_cost_usd` to date, `exits: "none"`. |

Failure isolation: any exception inside `build_desk` is logged and turns into a book note
("Autopilot seat unavailable: …") — the page never 500s over one seat. A missing book file is not
a failure: it renders as a dormant $100,000 seat with "no orders staged yet".

### 2.3 Inception and the picker

The Paper Desk's inception picker re-runs every card from a chosen date. The Autopilot cannot be
re-run: its orders were judgements made on their own day. Rule:

- The seat's window starts at **`book.card_adopted_date`** (2026-08-03 today), shown on the panel as
  "this seat's own inception, not the desk's".
- The picker is ignored for this seat, and the panel says so in one line. Fills before the desk's
  inception are still counted; hiding them would misstate the book.

### 2.4 Frontend

- `DeskKind` gains `"autopilot"`; `Desk.autopilot?: AutopilotDescription | null`.
- `DeskPanel`: badge reads `autopilot · full_workflow · screened universe`; the dormant note gets an
  autopilot variant ("No workflow order has filled yet. Last run 2026-09-01: no entry candidates
  fired.") instead of the rules-card sentence about an entry rule.
- `BookStatistics`: `kind === "autopilot"` renders `DeskAutopilotDescription` (the block above) with a
  link to `/agent-workflow`, in place of `DeskRules`.
- A one-line callout under the title: **"Holds forever: this workflow stages buys only."** Until §3.3
  is fixed, that is the single most important fact on the panel.
- `PaperDesk.tsx:409` tax filter (`kind === "rules"`) widens to `rules | autopilot`.
- Overview consumes the trading book's desks and is mid-edit by another session; re-check it renders
  a fourth kind once that lands.

### 2.5 Tests

- `tests/test_paperdesk_autopilot.py`: fixture book JSON with two fills, one pending, one rejected
  order; assert `equity == cash + positions_value`, holdings marked at `as_of`, pending → signal,
  rejected → grouped rejection, drawdown from the built curve, dormant on a missing file, malformed
  file → note not 500, `kind == "autopilot"` on the wire through `GET /api/paperdesk/state`.
- `DeskPanel.test.tsx`: autopilot fixture renders the badge, the holds-forever callout and the
  description block; an unknown future kind still renders.
- `test_frontend_contract.py` if it pins `DeskKind` (it does not today).

## 3. Fix first, or the card shows a broken feature honestly

1. **Equity curves are never written.** Either call `snapshot_equity` from `execute_pending`'s
   callers (daily step and `run_once`) or delete the field and let readers build curves from fills
   as §2.2 does. Recommend the latter: a curve derived from fills cannot drift from the ledger.
2. **`run_once` ignores the screen books.** The execute route now takes `universe_source`
   (uncommitted as of today); make `run_once` loop both sources too, so the in-process daemon fills
   the same books the scheduled task and the button do.
3. **No exit path.** Decide what closes a workflow position: the selected card's own `exit` / stop
   rules evaluated daily against the book's holdings (consistent with the "combination of strategy"
   framing), or a hold cap. Without this the Autopilot is buy-and-hold-forever and its return is
   mostly the market's.
4. **Backfill re-stages held names.** 117 of 130 null-arm orders were refused on the 25% cap because
   the symbol was already held. Apply the live pipeline's already-held skip (`pipeline.py:1103`) in
   `backfill_phase_b.py` too, or the Autopilot's rejections callout is noise from day one.
5. **Cap the rejection detail.** `_group_rejections` already caps at 20 sentences per rule; keep
   that for the autopilot desk.

## 4. Order of work — BUILT 2026-09-01

| Step | Status |
|---|---|
| §3.2 execute both universe sources | **Done by another session** (the execute route took a `universe_source` field mid-review). The in-process daemon `loop.run_once` still fills card books only. |
| `app/paperdesk/autopilot.py` + models block + `_book` branch | **Done.** No settings key was added — see below. |
| Frontend kind, panel, provenance block, default-visible | **Done.** |
| Tests | **Done.** 17 new backend tests, 17 new frontend tests. |
| §3.4 no-pyramiding | **Done**, and fixed one level up from the plan: the skip lives in the pipeline's own order staging, so it covers live runs and the backfill alike rather than patching the tool. Regenerating the backfill cut the null arm's ledger from 130 orders to 53. |
| §3.3 exit path | **Done** — `app/workflow/exits.py`, wired into both daily steps. See §7. |

**Deviations from the plan above, and why.**

* **No `paperdesk_autopilot_seat` / `paperdesk_autopilot_source` settings.** `rosters`' own docstring
  argues against inventing settings keys nobody sets, and `SAVINGS_AGENT_IDS`/`ROTH_AGENT_IDS` are
  precedent: seats here are hand-authored decisions with their reasoning recorded beside them. The id
  is appended to the trading roster in `rosters`, and unseating it is a one-line edit. `config.py`
  was also being edited by a concurrent session, which made avoiding it the safer call as well.
* **`build_desk` derives its own session calendar** instead of taking the desk's `session_dates`. The
  desk's sessions start at the desk's inception, which an operator has moved to 2026-08-27 — weeks
  after this book's first order. Reusing them truncated the seat's equity curve and understated its
  drawdown.
* **The block is headed "Provenance", not "Rules"**, and the empty universe line reads in words. A
  seat with no rules under a "Rules" heading is the exact mistake the ladder branch exists to prevent.
* **Holdings now carry real brackets.** §2's design table said each `Holding`'s
  `stop_price`/`target_price`/`sessions_to_time_stop` would be `None` "because the workflow applies
  none". Once the exit path (§7) landed, that stopped being true: the card's stop, take-profit and
  hold cap genuinely apply to the book's positions. So `_holdings` now derives all three from the
  selected card, exactly as `app.paperdesk.desk._holdings` does for a rules desk — a `None` only
  where the card itself declares that mechanism `None`, or where no card resolves. The seat's `exits`
  field likewise reports the real policy (`"12% stop, 120-session hold cap, and exit rule …"`), not
  the hardcoded `"none"`.
* **Two `filled_at` bugs fixed** — see §6.

## 6. A defect this work uncovered, and fixed

`WorkflowFillRecord.filled_at` is documented in its own docstring as "a wall-clock audit timestamp,
distinct from the order's own `fill_date` (the trading session the fill priced against)". Two places
used it as an acquisition date anyway:

* `app/workflow/book.py`'s `held_lots` — **pre-existing, and it corrupted tax output.** A lot's
  acquisition date is what both the holding-period split and the wash-sale window are measured from,
  so every figure `tax_summary` derives was being measured from the day a script ran rather than the
  day the trade happened. The deterministic backfill made it stark: it wrote a month of sessions in
  one pass, so every lot claimed to have been acquired that afternoon.
* `app/paperdesk/autopilot.py`'s own FIFO walk, written the same way.

Both now use `order.fill_date`. Before the fix, every Autopilot holding rendered with an entry date
of *today* and `bars_held = 0`; after it, the real sessions (2026-08-04, 2026-08-12) and holding
periods (20 and 14 bars). It stayed hidden because `tests/test_workflow_book.py` builds `filled_at`
as `datetime.combine(day, ...)` — consistent with the session by construction, which is precisely the
fixture that cannot tell the two fields apart. `tests/test_paperdesk_autopilot.py` now carries a
regression guard that sets them deliberately apart.

## 5. What the owner sees today — captured from the running app, 2026-09-01

A sixth panel in the Trading book, seated and visible on first load:

```
AUTOPILOT
AGENT-WORKFLOW   FULL_WORKFLOW · SCREENED UNIVERSE   NO TRADES SINCE INCEPTION

This desk only ever buys. Nothing it holds is ever sold by this workflow, and the
selected card's stop, target and hold-cap rules are never applied to these fills --
read its return with that in mind.

This desk has not opened a position since inception. The workflow has staged no order
that has gone on to fill, so it is holding its full starting cash — a flat return here
means it did not participate, not that it traded to a break-even. The last run
(2026-09-01 07:20 UTC) reported: no entry candidates fired.
```

and, under Book statistics, a **Provenance** block naming the arm and universe pair, the selected
card (`C-trend`, adopted 2026-08-03, labelled as this seat's own inception and immune to the
inception picker), the four order counts, the last run, the exits rule in words, and a link through
to the Agent Workflow desk. The Trading book itself carries two new notes: that this seat opens with
$100,000 against the book's $60,000, and that it runs from its own date.

**It is flat because the pipeline has found nothing, not because the card is broken** — and the
panel now says which, in the pipeline's own words. That distinction was the design's whole point.

The first fill appears the first weekday a screened candidate clears the gate and the
`Round33-PhaseB-Daily` task fills it at the next open.

**Proof the panel is right when it is not flat:** pointing `build_desk` at the null arm's book (130
orders, 5 filled, 125 rejected) yields equity $106,146.44 = cash $9,487.06 + positions $96,659.38
exactly, five holdings entered 2026-08-04 and 2026-08-12 with 20 and 14 bars held, max drawdown
−2.44%, capital exposure 0.955, rejections grouped into three reasons totalling 125, and a real
after-tax summary.
