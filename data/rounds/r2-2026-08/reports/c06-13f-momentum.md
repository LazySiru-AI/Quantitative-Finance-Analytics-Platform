# c06-13f-momentum -- 13F Conviction + Price Confirmation -- round 2 report

Agent: `c06-13f-momentum` | Discipline: `momentum` | **Unranked by construction, and this round the
toolchain enforces it rather than relying on a reader.** This must be read before any other number in
this report.

## 1. What the card is, its claim, and the provenance violation

Two chained signals: a universe of `GOOGL MSFT AMZN META NVDA AMD AVGO TSM`, selected as the eight
mega-cap/semiconductor names with >=4-manager 13F conviction as of the last filing legally visible
before the card's window opens; then a price rule, `close > sma(200) and close crosses_above sma(20)`,
requiring the market to still be actively re-rating the name before capital is risked. Exit `close
crosses_below sma(20)`, `stop_loss_pct = 0.12`, `max_positions = 4`, `position_pct = 0.20`. The card
declares `universe_knowable_from: 2025-11-14` -- the filing date the eight-name universe was actually
derived from.

**`CONSTRAINTS.md` is explicit: "A 13F-derived universe may only trade a window that begins after the
filing date it was derived from."** None of the eight main-matrix windows starts after 2025-11-14 --
`recent` starts 2025-08-21, three months *before* the filing date, and the other seven predate it by
years, one (`gfc`) by nearly two decades.

**This round the toolchain enforces that rule directly rather than depending on a reader to catch
it.** With `universe_knowable_from` declared, `results/eligibility.json` refuses all eight main
windows by name, and the scorecard flags the six run files the engine produced anyway as a
**PROVENANCE VIOLATION**, quoting the exact reasons:

> `universe knowable only from 2025-11-14, window starts 2020-02-19` -- this is basket lookahead
> (`PROTOCOL.md` §5), not an ordinary eligibility mismatch; `c06-13f-momentum` is reported as
> unranked.

The same reason recurs, with the window's own start date substituted, for `q4-2018` (2018-09-21),
`bear-2022` (2022-01-03), `chop-2015` (2015-04-07), `bull-2024` (2024-08-21) and `recent`
(2025-08-21). `covid` (2020-02-19) and `chop-2011` / `gfc` (guard-refused on separate, ordinary
grounds) round out the eight. **The only window this universe is legally eligible for is
`13f-legal`** (2025-11-17 -> 2026-08-18, three days after the filing date, per `WINDOWS.md`), created
specifically to give this card one legitimate test.

## 2. The one legitimate result, separated from six lookahead numbers

### `13f-legal` -- the only legitimate window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| 13f-legal | 188 | **+17.79%** | +14.60% | +3.19% | +10.99% | 46.6% | -12.49% |

56 trades, 46.6% capital exposure. **Note carefully: this is the same number round 1 produced
(+11.03%, a 0.04pp difference within the D2 engine-fix tolerance), recomputed on the same card, same
window, same data.** Per `REPORT.md` §7 and §1, the 13F result stands at exactly one draw, as it did
before round 2 ran at all. There is no median, IQR, or hit rate to report for one data point.

### Unmeasured -- basket lookahead, shown for completeness only, never as results

| window | sessions | card | SPY | excess | "adj. excess" | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| q4-2018 | 65 | -9.51% | -20.05% | +10.54% | -5.81% | 18.4% | -10.25% |
| covid | 93 | +18.97% | -8.71% | +27.68% | +23.81% | 55.6% | -7.06% |
| bear-2022 | 196 | -15.62% | -25.14% | +9.52% | -13.37% | 8.9% | -15.62% |
| chop-2015 | 260 | +11.51% | -0.04% | +11.55% | +11.53% | 54.9% | -10.94% |
| bull-2024 | 250 | -11.85% | +14.00% | -25.84% | -16.38% | 32.4% | -14.99% |
| recent | 249 | +22.44% | +20.62% | +1.83% | +12.13% | 50.0% | -12.07% |

These six numbers describe how a portfolio hand-picked from the fact that these eight names kept
working through late 2025 would have performed if traded starting as early as 2015 -- including
`bear-2022`, which predates every one of these companies' relevant 2025 institutional filings by three
years, and `chop-2015`, which predates them by a decade. They are not a measurement of this strategy.
Shown only because the brief asks for it, labelled, not scored.

## 3. What moved the legitimate number

56 trades in `13f-legal`. Exit-reason distribution: `rule` 53, `open_at_end` 3, `stop` 0.

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| AMD | 2026-04-01 | 2026-06-08 | 46 | rule | **+133.40%** | +2,494 | **+24.94%** |
| GOOGL | 2026-04-07 | 2026-05-26 | 34 | rule | +26.88% | +489 | +4.89% |
| TSM | 2026-04-02 | 2026-05-19 | 32 | rule | +19.06% | +312 | +3.12% |
| AVGO | 2026-04-08 | 2026-05-20 | 30 | rule | +17.24% | +303 | +3.03% |
| AVGO | 2026-07-09 | 2026-07-17 | 6 | rule | -9.08% | -183 | -1.83% |
| TSM | 2025-12-23 | 2026-02-05 | 29 | rule | +9.91% | +175 | +1.75% |
| AMD | 2026-06-09 | 2026-06-10 | 1 | rule | -7.01% | -141 | -1.41% |
| AMZN | 2026-08-03 | _open_ | 11 | open_at_end | -6.82% | -133 | -1.33% |

**A single trade -- AMD, entered 2026-04-01, exited 2026-06-08, 46 bars, +133.40%, +$2,494 -- is worth
+24.94% of the card's entire +17.79% return in its one legitimate window.** Even the legitimate result
rests heavily on one position: strip AMD out and the window's other 55 trades net to roughly -7.15%
of return on their own (the +17.79% total minus AMD's +24.94% share, allowing for compounding). There
was no stop-loss exit at all in this window (0 of 56) -- the card's own pre-registered risk ("a sharp,
fast drawdown specific to AI/semiconductor names... the previous-close stop check will realise worse
than 12% on a gap") was untested here because nothing breached the stop.

## 4. Concentration

Top-3 share of gross winning P&L in `13f-legal` is **81%**; without the three largest winners (AMD,
GOOGL, TSM) the card returns **-15.15%** instead of +17.79%. This is the most concentrated legitimate
result among the six cards in this report -- more concentrated than `C-trend`'s or `H-trend-
diversified`'s best windows, and resting on a single mega-cap melt-up rather than a diversified book
of eight names working together.

## 5. Realised versus marked

**-1.48%** of the +17.79% total sits in one open position (AMZN, -6.82% mark) at the window's close --
a small negative drag. The AMD trade itself, the one carrying nearly a quarter of the card's return, is
fully realised (`rule` exit, not `open_at_end`), so the headline number is not an artifact of the
window catching a position mid-run. That does not change the concentration finding in §4: it is a
realised result, but a realised result overwhelmingly dependent on one name.

## 6. Honest verdict: did the 13F step add anything measurable, and where this stands

**c06-13f-momentum is unranked by construction, and this is more prominent this round than last.**
Round 1 required a human reader to notice the lookahead and override an incorrect `"ranked": true,
15th of 18` scorecard entry. This round the scorer refuses the six contaminated windows outright and
labels them a provenance violation before any report is written -- the enforcement moved from
discipline to code, exactly as `PROTOCOL.md`'s amendment history records (`r2-2026-08: "Provenance is
enforced by code... caught by a reader, not a tool"` in round 1).

On the single legitimate window, the honest reading is unchanged from round 1: the card is genuinely
engaged (56 trades, 46.6% of a possible 80% capital ceiling), and the +17.79% return against +14.60%
SPY is real money, not lookahead-contaminated. But it is one draw, in a regime (continued mega-cap
tech advance) that is the opposite of every failure mode the card's own memo named in advance
(rotation away from mega-cap tech; a sharp AI/semiconductor drawdown; prolonged sideways chop) -- none
of which occurred, so the card was not tested against any of its own stated risks. And it rests
overwhelmingly on one trade: AMD's +133.4% single-name melt-up is +24.94% of the card's entire
legitimate result, on top of an 8-name universe that a naive "largest technology/semiconductor names
by market cap" screen would very likely have reproduced without touching EDGAR. The +10.99% adjusted
excess cannot be attributed to the 13F sourcing step versus a plain momentum screen on the same eight
obvious names; no counterfactual exists to make that comparison, a gap this card's own memo names
honestly.

**Recommendation: unranked, and hold there -- do not promote, and do not retire.** `PROTOCOL.md` §6
has no promotion path for a card that cannot clear the regime gate, and the structural reason it
cannot -- the engine holds one frozen universe for an entire window, while a 13F-derived basket is
knowable only from its filing date forward -- is not a data gap that a future round's calendar
progress fixes on its own. Every future main window this program adds will, by definition, need to
start after whatever filing date backs the universe in force at the time, or it repeats exactly this
violation. This is not a retirement case (the card takes trades and has one legitimate positive
result), but it should not be re-scored on the six contaminated windows in any future report, and any
comparison of this card to the ranked field should state plainly that it has exactly one legitimate
data point, unchanged since round 1.
