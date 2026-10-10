# Definitions — what every headline statistic actually means

Four defects in one UAT run were the same shape: **a number computed correctly, under a label that
meant something else.** Not arithmetic errors — the arithmetic was checked to the cent and held.
A cash "settled" figure that exceeded the balance; a "Current drawdown" that reported the ongoing
episode's worst bar; "Still underwater: no" two rows from a live drawdown; a tax message asserting a
count it never took. Every unit test passed throughout, because every test asserted the computation
and none asserted the *claim*.

So this file is the register of claims. One row per statistic a user reads without drilling in:
what the label says, what the code computes, and where. `tests/test_definitions.py` asserts that
every fact the report bundle can emit appears here — a new statistic cannot ship without a stated
definition.

**Where a name is ambiguous, the label carries the disambiguation, not this file.** A register
nobody opens does not prevent a misreading on a page. This exists to make the next label reviewable,
not to substitute for one.

---

## Sample and provenance

| Label | Means | Computed in |
|---|---|---|
| `Sessions` / `<interval> bars` | Count of bars in the sample. **Says "Sessions" only on daily bars** — at `1h` it says `1h bars`, because 3,400 hourly bars is ~485 sessions and labelling them sessions overstates the sample seven-fold. | `report/builder.py:_sample_facts` |
| `First session` / `First bar` | Date of the earliest bar in the sample. Wording follows the interval, as above. | same |
| `Last session` / `Last bar` | Date of the latest **stored** bar — not today. The portfolio prices from this, so marks can legitimately post-date a session being reviewed. | same |
| `Last price` | Latest quote from the provider, not the last stored bar. A different number from the one bars are priced at, deliberately. | `report/builder.py:_instrument_facts` |

## Drawdown

The two questions a live decline answers are different, and conflating them was the run's most
serious label defect.

| Label | Means | Computed in |
|---|---|---|
| `Current drawdown` | **Peak to the latest observation.** How far below the running high the price is *now*. | `backtest/drawdown.py:_episode` → `DrawdownEpisode.depth_now` |
| `Current drawdown as of` | The bar `Current drawdown` is measured at. Normally the last bar; earlier when the final prints are missing, because a gap never silently participates in a figure. | same |
| `Current episode worst` | Peak to **trough** of the still-open episode. How bad it has been, not where it is. | `DrawdownEpisode.depth` |
| `Deepest drawdown` | Peak-to-trough depth of the single worst episode in the whole history. | same |
| `Deepest episode …` | Every field prefixed this way describes **that** episode, not the live one. The prefix is load-bearing: "Still underwater: no" and "Current drawdown −15.6%" were both true, of different episodes, and sat two rows apart. | `report/builder.py:_drawdown_facts` |
| `Drawdown episodes` | Total episodes found **before** top-N truncation, so a top-10 table cannot be read as the whole history. | `DrawdownProfile.episodes_considered` |
| `Strategy max drawdown` | Max drawdown of the strategy's **equity curve** — a different series from the price drawdowns above. | `backtest/metrics.py:_max_drawdown` |

Episodes tile the series without overlapping: two dips to the same trough are one episode. For the
`intraday` basis the peak and recovery test use `high` and the trough uses `low`; "now" is measured
on `high`, the column that would actually end the episode.

## Rule evidence

| Label | Means | Computed in |
|---|---|---|
| `Hit rate vs baseline` (a.k.a. the `Edge` column) | Hit rate **minus** baseline hit rate, in percentage points of *how often*, expressed as a fraction. `0.12` is twelve points more often than the instrument does anyway — **not** a 12% return. | `rules/models.py:Evidence.edge` |
| `Median return vs baseline` | Median forward return minus the unconditional median over the same sample and horizon. | `rules/evidence.py` |
| `Sample` / `Independent observations` | The **non-overlapping** trigger count. Overlapping forward windows are not independent draws; every significance judgement uses this, never the raw count. | `backtest/forward.py:independent_count` |
| `Horizon (bars)` | Forward-return horizon in **bars**, not calendar days. | `rules/models.py:HORIZONS` |
| `Significance` | A coarse grade, **not** a p-value or a significance test. `suggestive` needs ≥30 independent triggers *and* ≥8 points of edge; `weak` needs ≥8 *and* ≥15 points; everything else is `insufficient`. Both conditions must hold together. Thresholds travel to the UI on `DecisionTable.criteria`. | `rules/evidence.py:_significance` |
| `Rule with the largest edge` | The **name** of the rule with the largest absolute edge. Selecting by magnitude systematically favours the smallest sample, which is why the grade is emitted beside it. | `report/builder.py:_rule_facts` |
| `Rules firing` | Rules currently true on the most recent **settled** bar. | `rules/service.py` |

## Strategy backtest

| Label | Means | Computed in |
|---|---|---|
| `Trades opened` | Every trade the strategy **opened**, including one still open on the last bar. | `backtest/metrics.py` → `StrategyMetrics.trades` |
| `…of which still open` | A **subset** of the above, not an addition. Labelled "Trades (closed)" beside "Open at end" until 2026-08-14, which invited adding the two. | `StrategyResult.open_trades` |
| `Win rate (closed trades)` | Winners over **closed** trades only. A different denominator from `Trades opened` — a position with no exit has no outcome to score. | `backtest/metrics.py:_win_rate` |
| `Time in market` | Fraction of bars holding a position. A strategy in the market 4% of the time carries 4% of the risk; comparing its raw return to buy-and-hold without this is the second-commonest way to make a rule look good. | `StrategyMetrics.exposure` |
| `Strategy CAGR`, `Sharpe`, `Sortino`, volatility | **Withheld (`null`) under one year of data.** Annualising a short sample produces a figure shaped like a rate that the sample cannot support — a few days of noise yields a Sharpe of 5–11. | `backtest/metrics.py` |
| `Cost drag` | Total return with frictions minus total return without them. Always ≤ 0. A strategy whose entire edge sits inside this has no edge. | `StrategyResult.cost_drag` |
| `Excess over buy-and-hold` | Strategy total return minus buy-and-hold total return over the identical window, computed by the same code. | `report/builder.py:_strategy_facts` |

## Portfolio and cash

| Label | Means | Computed in |
|---|---|---|
| `Cash` | Sum of the ledger's cash movements for accounts where a balance can be **derived at all**, or the user's own **declared** figure (`CashVerdict.DECLARED`, from `[[cash]]` in the account manifest) where the export carries no cash rows to derive one from. Partial whenever `accounts_without_cash` is non-empty, and the tile says `(partial)`. A declared balance is a snapshot, not a running total — it does not move as new transactions import, and the UI states the date it was read off the broker beside it. | `core/cash.py:build_cash` |
| `settled` | `balance − unsettled`, and therefore **never more than the balance**. Answers "what can I deploy". | same |
| `unsettled` | **Proceeds** not yet settled — positive only. A purchase awaiting settlement is already deducted from the balance and is not money coming back; counting it made `settled` exceed the balance. | same |
| `Total equity` | Cash + market value, and `null` unless **both** halves are complete. Unlike its components there is no honest partial version: it is read as *the* answer to "what is this worth". | `api/portfolio.py` |
| `Weight (of invested)` | Share of priced **market value**. Sums to ~100% with cash outside it, which is why it says "of invested". | `api/portfolio.py` |
| `Market value`, `price` | Quantized to cents at the pricing boundary. The bar store holds 32-bit floats, so `777.8800048828125` is the stored image of a $777.88 close. | `api/portfolio.py:_price` |
| `Ledger as of` / `priced at the close of` | Two different dates. The first is the latest transaction; the second is the pricing date, and the stamp says outright when it mixes several. | `frontend/src/pages/Portfolio.tsx` |

## Tax

| Label | Means | Computed in |
|---|---|---|
| `Wash-sale disallowed (deferred)` | Loss disallowed under §1091 and **added to the replacement lot's basis** — recovered on a future sale. | `tax/washsale.py` |
| `Permanently disallowed (IRA)` | Rev. Rul. 2008-5: replacement bought in an IRA. **No basis add-back anywhere.** Never summed with the deferred figure into one number. | same |
| `Deferred disallowed` (per-symbol panel) | The same deferred figure as `Wash-sale disallowed (deferred)` above, folded to one row per symbol. Already added to a replacement lot's basis; recovered only when that lot is sold and is not itself re-replaced within 30 days. **Not released by the "Days until safe" countdown on the same row** — see the note below the table. | `tax/washsale_summary.py:build_wash_sale_summary` |
| `Permanently disallowed` (per-symbol panel) | Same distinction as `Permanently disallowed (IRA)` above, per symbol. Never summed with `Deferred disallowed`. | same |
| A row showing `$0.00` deferred with an open window | Not an empty row — the **most actionable** one. It is a loss that has not been bought back yet, so nothing has been disallowed and nothing is deferred. Repurchasing before `Repurchase safe on` is what would create the wash sale. | `tax/washsale_summary.py` |
| `Loss sales` | Count of **distinct loss disposals** for the symbol in a taxable account — whether or not any of them triggered a wash sale. Not the event count: one disposal split across a taxable and an IRA replacement produces two events from a single sale. | `tax/models.py:WashSaleSymbolSummary.loss_sale_count` |
| `Last sale date` | The symbol's most recent **loss sale**, triggered or not. `Repurchase safe on` is measured from this date, not the earliest one. Reading it from triggered sales alone is what produced the false "safe" claims described below. | `tax/washsale_summary.py` |
| `Repurchase safe on` | `last_sale_date + 31 days`. §1091 reaches 30 calendar days after a sale, inclusive; the 31st day is the first on which a repurchase does not land back inside that window. Full rule and citations live in `tax/washsale.py`'s module docstring — not restated here. | same |
| `Days until safe` | `max(0, repurchase_safe_on − today)`. **The one clock-dependent figure in this panel** — every other value in it follows only from historical events, not from when the page happens to be loaded. Clamped at zero, so a long-closed window reads `0`, never a negative countdown. | same |
| `window_is_open` | `today ≤ last_sale_date + 30`. The boolean behind whatever the panel renders as a status; true means a repurchase today would disallow the loss on that most recent sale. | same |
| `first_sale_date` | Earliest loss sale for the symbol. Context only — the **latest** sale is what sets `repurchase_safe_on`, because its window closes last. | same |
| `Gain/loss` in the disposals table | **Reportable** — after any §1091 disallowance. Not proceeds minus basis. | `tax/gains.py:GainRow.reportable_gain_loss` |
| `Nothing was disposed of in <year>` | Distinct from "no activity in the year" and from "nothing imported". A year with buys and no sells legitimately reports zero gains and is not an absence of data. | `frontend/src/pages/Tax.tsx` |
| `lot_method` | `null`, not `"fifo"`, on an oversold shortfall — no lot was consumed, so no rule chose one. | `core/lots.py` |
| `GET /api/tax/wash-sales` `total_deferred` / `total_permanently_disallowed` | The **whole-ledger** sums of every symbol's `Deferred disallowed` / `Permanently disallowed` above — same two figures, same never-summed rule, at the report level instead of per symbol. Not year-scoped and the endpoint takes no `year` — see the scope note below. | `tax/washsale_summary.py:build_wash_sale_exposure_report` |
| `open_window_count` | Count of symbols carrying `window_is_open = true`. A symbol counts once here regardless of how many of its individual sales are still inside their own window. | same |
| `symbol_count` | Number of rows in the tracker's `symbols` list — every symbol with at least one loss sale in a taxable account, triggered or not. | same |
| Exposure tracker symbol order | **Open windows first**, then `Deferred disallowed` descending, then symbol ascending. Deliberately not the same order as the Tax report page's own per-symbol panel, which sorts by size alone — the tracker exists to answer "what is still live", so a small open window outranks a large, fully-settled one. | same |
| `sales` (per-symbol drill-down) | The individual loss disposals behind one symbol's totals: one row per triggered wash-sale event, **plus one zeroed row for every loss sale that triggered no event at all**. The second kind is the same "$0.00 deferred, open window" case described above, now shown at the sale level with its real `loss_amount` and `quantity_sold` — `disallowed_loss` and `quantity_replaced` read zero because nothing has matched yet, not because nothing was lost. `sales.length` can exceed `event_count`; the two answer different questions. | `tax/models.py:WashSaleSaleRow` |
| `window_closes_on` (per sale) | `sale_date + 31 days` — **this sale's own window**, not the symbol's. Differs from the symbol-level `Repurchase safe on` whenever a symbol has more than one loss sale: `Repurchase safe on` is measured from the symbol's *latest* sale, so an earlier sale's own window can close well before the symbol as a whole is safe to repurchase. | same |
| `as_of` (tracker) | Same meaning as `as_of` on the Tax report's per-symbol panel — the date `days_until_safe`/`window_is_open` are measured from, defaulting to today. | `tax/models.py:WashSaleExposureReport` |
| `generated_at` (tracker) | Wall-clock time the response was built. Not the same date as `as_of` — a request made shortly after midnight can carry a `generated_at` timestamp on one calendar day and an `as_of` date reflecting the other, since `as_of` is a date, not a moment. | same |

`Deferred disallowed` and `Days until safe` sit on the same row of the per-symbol panel and answer unrelated
questions. The dollar figure is already inside a lot's basis; no amount of waiting releases it — only
selling that lot, without it being itself replaced inside another 30-day window, does. The countdown
instead protects a *different, future* transaction — the next repurchase — from triggering §1091 again.
Reading the two together as "safe to buy back in 9 days, then the $12,340 comes back" is the misreading
this panel invites, which is why the two figures are documented separately here rather than as one
combined story. (Both figures there are invented — this file carries no real balances, for the same
reason `data/` is gitignored.)

The panel is built from **every loss sale in a taxable account**, not only from the ones that
triggered a disallowance. That distinction is the difference between a correct answer and a
confidently wrong one: a `WashSaleEvent` exists only where a loss has *already matched a replacement
purchase*, so a loss still sitting unrepurchased — the exact case a user opens this panel to check —
emits no event at all. Anchoring the dates on events alone reported three symbols as safe to
repurchase while their windows were genuinely open, and omitted three more with open windows
entirely. See `tax/washsale_summary.py`'s module docstring for the measurement.

`GET /api/tax/wash-sales` takes **no `year` parameter**, unlike `/report`. This is not an
oversight: the per-symbol panel it serves has always been whole-ledger scoped regardless of which
year `/report` happens to be showing (see the scope comment above `wash_sale_summary = ...` in
`tax/engine.py:build_tax_report`), because "what is deferred right now, and when can I buy this
back" does not reset at a calendar boundary the way gains and Form 8949 do.

On this user's data specifically, `deferred_disallowed` runs large relative to the portfolio, and most of
it resolves within the same tax year: it unwinds when the replacement lot that received the adjustment is
itself sold. Only the fraction still sitting in lots open at year end carries forward past December 31.
That is a property of this data, not of the rule — §1091 does not expire at year end, and a lot that
stays open longer simply keeps its adjusted basis until it is eventually sold.

## Macro

| Label | Means | Computed in |
|---|---|---|
| Fear & Greed `Score` column | The component's 0–100 contribution. **Empty on a CNN-sourced reading** — CNN publishes each component's raw value and rating but never the normalisation. Only the local composite computes it. | `market/fear_greed.py` |
| Fear & Greed component `Raw` | The component's own measurement, in its own unit (`index`, `ratio`, `pp`), **not comparable across components**. The unit is rendered beside it. | `market/macro_models.py:FEAR_GREED_UNITS` |
| `Composite (approximation)` badge | The score was computed locally, not published by CNN. The composite cannot reproduce CNN's number, only approximate it — CNN publishes component raw values but not its weights or normalisation. | `market/fear_greed.py` |

---

## Institutions (SEC filings)

Every row on this page is read from a filing that was already months old when it became public.
Two of the four defects found while building it were label defects of exactly the kind this file
exists to catch — a figure computed correctly, presented under a word that meant something else.

| Label | Means | Computed in |
|---|---|---|
| `Action` — Add / Trim / New / Exit / Hold | Derived from the **share count alone**. A position whose dollar value moved but whose share count did not is `Hold`, however large the dollar move. Berkshire's Chevron stake fell $3.47bn across one quarter on a share count that did not change by a single share; classified on value it reads as the quarter's largest sale, and no sale occurred. | `institutions/deltas.py:diff` |
| `Shares Δ` | `shares_after - shares_before`. The decision, isolated from the market. | `institutions/deltas.py` |
| `Value Δ (incl. price)` | `value_after - value_before` — trading **and** repricing, inseparably. Can carry the opposite sign to `Shares Δ` on the same row: Berkshire sold 30,230,150 shares of Bank of America and the position still gained $2.50bn. | `institutions/deltas.py` |
| `Shares % chg` | `shares_delta / shares_before`, a **fraction of one** on the wire, rendered as a percent. `new` — never `0%` or `∞` — when there was no prior position to divide by. | `institutions/models.py:HoldingChange` |
| `Weight` / `Weight Δ` | Share of **the total value disclosed in this filing**, not of the filer's net assets or of their whole book. A 13F covers US-listed equities only, so a 13F weight is a weight within that slice. Rises when the holder buys *and* when the rest of the book falls. | `institutions/parse.py`, `institutions/deltas.py` |
| Median share change (the note under the counts) | Median `shares_pct_change` over `Add` and `Trim` rows only. Exits (always exactly −100%) and holds (always exactly 0%) are excluded because including either measures something other than trading. **States the statistic, names no cause** — a tight cluster is the signature of a fund changing size *or* of an index reconstituting, and this data cannot tell them apart. QQQ: 99 positions, −6.07%. SCHD: 76, −22.64% (a reconstitution). Berkshire: 13, +3.65%. | `institutions/models.py:PortfolioDelta.median_shares_pct_change` |
| `Identifier` column | The CUSIP where the filing carries one. Not every row does — a foreign listing may disclose only an ISIN, and the parser keys it `ISIN:…` rather than dropping the holding. The column is **not** headed CUSIP for that reason. | `institutions/parse.py` |
| `YOU OWN THIS` badge | This CUSIP matches an instrument in the user's own ledger. Absence means **no CUSIP match**, not "you don't own it" — many ledger instruments carry no CUSIP at all (AAPL among them for a real multi-broker ledger), so a real holding can go unbadged. | `institutions/catalog.py:ledger_cusip_tickers` |
| Ticker, anywhere on the page | Resolved only through that same ledger match. Neither filing carries a ticker and no free SEC endpoint maps CUSIP to ticker, so most rows have none and show the issuer name instead. A ticker here is never inferred from an issuer name. | `institutions/catalog.py:apply_tickers` |
| `Comparing <period>` / accession numbers | The **as-of** dates, not the filing dates, and the two do not sort alike — iShares filed a report for 2025-09-30 *after* one for 2026-03-31. Ordering on the filing date runs the comparison backwards. | `institutions/deltas.py:latest_pair` |
| `Values rescaled ×1,000` | This filer stated its `<value>` column in thousands despite the 2023-Q1 rule requiring whole dollars, and the parser multiplied it up. **A judgement about someone else's data, not their disclosure**, which is why it is said on screen rather than applied silently. Detected from the median implied price (`value / shares`) across the book: a correctly scaled 13F implies prices in the tens or hundreds of dollars, a thousands-scaled one implies cents. Duquesne Family Office's quarter ending 2026-06-30 reads $5.2m literally and $5.21bn rescaled; its 72,900 AMD shares imply $0.58 each on a day AMD closed at $517.82. | `institutions/parse.py:_looks_like_thousands` |
| Filer name, e.g. `Cathie Wood — ARK Investment Management LLC` | The firm is what filed; the person is an **editorial label** from the watchlist, never from EDGAR. Omitted where naming someone would be a claim about the past rather than the present — Renaissance's founder died in 2024, Lone Pine's stopped managing money in 2019. It never asserts that this person chose any individual holding: a 13F is filed by a firm. | `institutions/catalog.py:_MANAGERS` |
| ARK, twice | `ARKINVEST` (13F) is every account ARK Investment Management runs, aggregated. `ARKK` (NPORT-P) is the one ETF. Different filings, different scopes, deliberately both present and never merged. | `institutions/catalog.py` |

## Standing rules this register encodes

1. **A label names the quantity, not the neighbourhood.** "Current drawdown" is a claim about now.
2. **Where two figures could be confused, the label disambiguates both** — `Trades opened` and
   `…of which still open`, `Current drawdown` and `Current episode worst`.
3. **Units belong in the label** when the number alone does not carry them: percentage points of
   *how often* versus percent of return; bars versus sessions versus calendar days.
4. **A withheld figure renders `—`, never `0`.** Zero is a measurement.
5. **Annualised figures are withheld under a year**, rather than shown with a caveat.
6. **Two statistics shown together were computed over the same window by the same code**, or they
   are not shown together.
7. **A static dollar figure and a clock-relative countdown are different claims even sharing a row.**
   The wash-sale panel's `Deferred disallowed` doesn't move until a lot is sold; `Days until safe`
   ticks down every day regardless. Neither implies the other.
8. **A count of rows is not a count of decisions.** An index fund does not choose its holdings one
   at a time; when it changes size every position moves together and a naive diff reports one
   `Trim` per holding. The counts strip is qualified by the median share change beside it, which
   says how tightly those moves cluster — and stops short of naming the cause, because the same
   signature has more than one.
