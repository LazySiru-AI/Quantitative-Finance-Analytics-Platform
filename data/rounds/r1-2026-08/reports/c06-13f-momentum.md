# c06-13f-momentum — 13F Conviction + Price Confirmation

**Special case — read this before the table.** The official scorecard (`results/scorecard-full.json`)
marks this card `"ranked": true`, 15th of 18, with a median adjusted excess built from the `covid`,
`bear-2022`, `bull-2024` and `recent` windows. **That ranking is wrong and must not be used.** The
card's universe (`GOOGL, MSFT, AMZN, META, NVDA, AMD, AVGO, TSM`) was derived from 13F filings legally
knowable only from **2025-11-14**; per `CONSTRAINTS.md`, "a 13F-derived universe may only trade a
window that begins after the filing date it was derived from." None of the four main-matrix windows the
scorecard used starts after that date — `recent` starts 2025-08-21, three months *before* the filing
date, and the other three predate it by years. Every trade the runner recorded in those four windows is
a portfolio picked with knowledge of which mega-cap tech names would work, run over calendar time that
predates the document that justified picking them. This is the identical construction error the prior
tournament made with three 13F cards and that this program's own `CONSTRAINTS.md` names as a documented
failure. The scoring machinery has no way to know a basket's legality window, only whether the run
completed and the symbol-level lookahead guard passed — both of which it did, cleanly, in all four
contaminated windows. That the guard passed is not evidence the run is valid.

The only window this universe is legally eligible for is the special `13f-legal` window
(2025-11-17 → 2026-08-18, benchmark +14.60%), created specifically to give this card one legitimate
test. **By the letter of the brief's own gate — fewer than three eligible windows reports as
unranked — this card is unranked**, exactly like `D-13f-newbuys` and `E-asymmetric` already are in the
official scorecard. It should be reported the same way, not as 15th of 18.

## 1. What the card was

Two chained, independent signals. **Universe (13F, not traded directly):** pool every `NEW`/`ADD` row
(classified by disclosed share-count change only, never value, so a price repricing is never misread as
a trade) from all 14 managers in the catalog as of the filing date, resolve CUSIP → ticker through the
project's ledger-scoped bridge (no issuer-name fallback, per the assignment's explicit prohibition), and
keep only names with ≥4-manager conviction and enough bar history to warm up `sma(200)` before the
window opens. **Entry (price, momentum):** `close > sma(200) and close crosses_above sma(20)` — the 13F
step says a name was worth institutional accumulation as of the last legally visible filing; the price
rule says the market is still actively re-rating it, not merely being held on paper. The mechanism
argument is that a multi-billion-dollar manager's new position is built over weeks, not one session, and
that continued 13F-driven buying by other participants who read the same filings is met by
disclosure-indifferent counterparties — retail or passive flow. `exit`: `close crosses_below sma(20)`.
`stop_loss_pct = 0.12`. `max_positions = 4`, `position_pct = 0.20` (80% ceiling, not relying on the
round's relaxed 100% single-name cap). 6 of 10 parameters used.

## 2. Results — the legitimate window, separated from the lookahead-contaminated ones

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1`, `capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions ×
starting_equity)`, `adjusted_excess = corrected_return − capital_exposure × benchmark_return`.

### The one legitimate result

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **13f-legal** | 56 | **+17.79%** | +14.60% | +3.19% | **+11.03%** | 46.28% | 89.89% | −12.49% | 30.19% |

n = 1 window. There is no median, no IQR, no hit rate to report for this card that means what those
figures mean for a five-window card — a single data point cannot be scored against the brief's own
"consistency across regimes" standard, because there is no second regime to be consistent with.

### Unmeasured — basket lookahead, shown for completeness only, not as results

| window | trades | corrected return | benchmark | excess | "adjusted excess" | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 21 | +18.97% | −8.71% | +27.68% | +23.73% | 54.71% | 79.57% | −7.06% | 29.41% |
| bear-2022 | 25 | −15.62% | −25.14% | +9.52% | −13.37% | 8.95% | 24.49% | −15.62% | 12.00% |
| bull-2024 | 59 | −11.85% | +14.00% | −25.85% | −16.36% | 32.25% | 65.20% | −14.99% | 24.56% |
| recent | 77 | +22.44% | +20.62% | +1.82% | +12.17% | 49.82% | 93.57% | −12.07% | 31.08% |

These four numbers describe how a portfolio hand-picked from the fact that `GOOGL`/`MSFT`/`AMZN`/
`META`/`NVDA`/`AMD`/`AVGO`/`TSM` kept working through late 2025 would have performed if traded starting
as early as 2007 — including one leg, `bear-2022`, that predates every one of these companies' relevant
2025 institutional filings by three years. They are not a measurement of this strategy. Reported here
only because the assignment asks for them to be shown, labeled, not scored.

## 3. Pre-registered failure regime versus what happened

The memo names three failure regimes, verbatim: *"A rotation away from mega-cap tech... even if the
broad market is flat or up"*; *"A sharp, fast drawdown specific to AI/semiconductor names"*, noting the
`sma(200)` filter is "structurally late" and the previous-close stop check will realize worse than 12%
on a gap; and *"A prolonged sideways chop in these names"* producing "a string of small losses through
the stop or the crosses-below exit."

**None of the three occurred in the one legitimate window.** `13f-legal` (2025-11-17 → 2026-08-18) ran
through a continued mega-cap tech/semiconductor advance — the benchmark itself returned +14.60%, and
the card's own best trade (`AMD`, 2026-04-01 → 2026-06-08, +133.4%, +$2,493.51) is a single-name melt-up,
the opposite of a rotation away from the theme. There was no stop-loss exit in this window at all (see
§4), so the gap-fill concern was untested. The low win rate (30.19%) is the one data point that partly
matches the "sideways chop, string of small losses" texture the memo predicted — most of the 56 trades
were small losers closed by the `crosses_below sma(20)` exit — but the aggregate result was still
strongly positive because a handful of large winners (`AMD` chief among them) outweighed the many small
losses. The honest read is that the card was not tested against any of its own named risks; it got a
favorable regime on its one legitimate look, which validates nothing about how it would behave in the
regime it fears.

## 4. Trade-level detail

**Exit-reason distribution, `13f-legal`:** `rule` 53, `open_at_end` 3, `stop` 0.

**Best and worst trades, `13f-legal`:** best `AMD`, 2026-04-01 → 2026-06-08, rule, **+133.40%**
(+$2,493.51, 46 bars held); worst `AVGO`, 2026-07-09 → 2026-07-17, rule, −9.08% (−$182.65, 6 bars
held). (These are the same two trades that appear as best/worst in the contaminated `recent` window —
`13f-legal` is almost entirely nested inside `recent`'s date range, so the overlap is expected, not a
data error.)

**Stop-outs against the nominal 12% stop: zero in the legitimate window.** There is exactly one
stop-loss exit anywhere in this card's entire run, and it falls in the contaminated `bull-2024` window:
`TSM`, entered 2025-01-16 at $219.00, stopped 2025-01-28 at $195.55 — a realised loss of **−10.71%**
against the 12% nominal stop. This is worth flagging precisely because it runs the *opposite* direction
from the general pattern documented in `CONSTRAINTS.md` (stops evaluated against the previous close
fill worse than nominal): here the trigger session's close had already breached the −12% threshold, but
the fill at the next session's open recovered part of the gap before execution, landing the realised
loss 1.29 points *better* than nominal. Gaps cut both ways; this one happened to help. Since this trade
sits in a lookahead-contaminated window and the legitimate window produced zero stop exits, the card has
no legitimate observation yet of how its stop actually behaves.

## 5. Defended versus abstained

In the one legitimate window, the card is genuinely engaged: 56 trades, 46.28% capital exposure against
an 80% ceiling (`max_positions=4 × position_pct=0.20`), and 89.89% of sessions holding at least one
position — closer to full deployment than restraint, with headroom against the ceiling still
unused. This is a card that traded, not one that mostly sat out its single test. The contaminated
windows (shown in §2 for completeness) span a wider range — capital exposure from 8.95%
(`bear-2022`) to 54.71% (`covid`) — but say nothing trustworthy about this card's actual behavior, since
they trade a universe that could not have existed in the manager's information set on those calendar
dates.

## 6. Honest verdict: did the 13F step add anything measurable?

The author's own memo concludes it mostly did not — "momentum with an elaborately-derived but
conventional universe" is the fair characterization, not "13F selection found something the market
hadn't priced in." That verdict holds up under scrutiny and deserves to be sharpened rather than merely
repeated. The pipeline is real and was run as specified: 14 managers, share-count-only classification,
3,237 `NEW`/`ADD` rows, a CUSIP-only ledger bridge that resolved 134 of them (4.1%, matching the brief's
~3.7% estimate for the bridge generally), 85 with tradeable bars, collapsing under a ≥4-manager
conviction filter to eight names that are, without exception, the most obviously-owned mega-cap
technology and semiconductor stocks in the market during this period. A universe built by screening for
"largest technology/semiconductor names by market cap" would very likely have landed on a materially
overlapping set without touching EDGAR. The 13F machinery did contribute three concrete, verifiable
things: a documented and reproducible selection process rather than a hand-picked list; a real exclusion
(`FIG`, dropped correctly for insufficient pre-window bar history despite 4-manager conviction) driven
by a data constraint rather than narrative judgment; and visibility into the layer just below the
consensus cutoff (`NET`, `QCOM`, `CRDO`, `OKLO`, `NBIS`, `IREN` at 2–3 manager conviction) that a naive
market-cap screen would not have surfaced at all. None of that is evidence of predictive value added by
the 13F step — no counterfactual "same price rule, generic mega-cap universe, no EDGAR" run exists to
compare against, a gap the author's own memo names honestly. With exactly one eligible window and zero
counterfactual, the +11.03% adjusted excess in `13f-legal` cannot be attributed to the 13F sourcing
versus a plain momentum screen on the same eight obvious names; it is one favorable regime observed
once.

**Retire the 13F-sourcing approach as currently implemented.** Two structural problems compound rather
than one: first, the CUSIP bridge resolves roughly 4% of raw disclosed positions, which mechanically
biases whatever survives toward the most liquid, most widely-held, most ledger-visible names — exactly
the consensus trade rather than a differentiated one; second, and more fundamentally, `CONSTRAINTS.md`
is explicit that **the engine cannot rotate a universe mid-window**, so any 13F card is a single stale
snapshot held for the entire run regardless of how the pipeline is refined. The mechanism this card
argues for — continued institutional accumulation as filings roll forward — cannot be expressed by a
harness that freezes the universe at window open. Improving the CUSIP bridge or the conviction threshold
would change which eight names get picked; it would not change the fact that the resulting card is
structurally limited to one un-refreshable snapshot and, currently, to exactly one legally eligible
window, which by the brief's own gate is unrankable no matter how the pipeline performs.

**If this space is tried again**, the more informative next step is not a better bridge but a
deliberately different filter: build the universe from the 2–3 manager, sub-consensus names the memo
already surfaced and discarded (`NET`, `QCOM`, `CRDO`, `OKLO`, `NBIS`, `IREN`) rather than the ≥4-manager
tier that collapses to mega-cap consensus by construction. That is the one genuinely untested hypothesis
this round's pipeline produced — whether 13F conviction below the obvious-name threshold carries any
signal at all — and it would still face the same single-window eligibility ceiling, so it should be
understood in advance as a research probe, not a rankable card.
