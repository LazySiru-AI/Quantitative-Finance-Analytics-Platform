# c06-13f-momentum — design memo

Agent id: `c06-13f-momentum` · discipline: `momentum` · designed through: `2026-02-13`

## 1. Mechanism

Two independent signals, chained:

1. **Universe selection (13F, not traded directly).** A 13F manager's disclosed share count is the
   only field trusted for a buy/sell classification (`app/institutions/deltas.py` classifies
   `NEW`/`ADD`/`TRIM`/`EXIT`/`HOLD` from share count alone, never from value, precisely so a price
   repricing is never misread as a trade — see that module's own Chevron/Berkshire example). A
   `NEW` or `ADD` filed by a multi-billion-dollar manager cannot, mechanically, be filled in one
   session without moving the market the manager trades in; size forces the position to be built
   over weeks, sometimes across more than one quarter. The 45-day filing lag means the signal is
   never fresh, but the *building* it discloses is often still in progress when the filing becomes
   public, and other participants who read 13F disclosures add their own buying on top of it. The
   counterparty on the other side of that continued buying is not pricing in what the filing just
   revealed — typically a retail seller or an index/passive flow indifferent to the disclosure.
2. **Entry timing (price, momentum).** The 13F selection only says a name was worth institutional
   accumulation as of the last legally-visible filing before this card's eligible window opens. It
   says nothing about *when* to buy. The price rule requires the stock to already be in an
   established uptrend (`close > sma(200)`) and to have just pushed through a fresh short-term high
   (`close crosses_above sma(20)`) — i.e., the market is still actively re-rating the name, not that
   institutions merely own it on paper while it drifts or falls.

This card **does not trade the 13F signal directly** per the mandate — the universe is fixed from a
single pre-window snapshot of institutional conviction, and every entry/exit decision inside the
window is driven purely by price.

## 2. Universe — how it was built, and what it collapsed to

**Constraint respected:** the assignment's window-start rule (`13f-legal` starts 2025-11-17) means
the universe must be derivable only from filings **filed on or before ~2025-11-14** — the Q3-2025
13F deadline — not from the fuller `as_of=2026-02-13` design cutoff, which would let in Q4-2025
filings some large managers (ARKINVEST, SOROS, BRIDGEWATER, RENTECH) filed in February 2026, i.e.
*inside* the trading window. Using those would violate "a 13F-derived universe may only be traded in
a window that starts after the filing date it was derived from." All queries below therefore use
`as_of=dt.date(2025, 11, 14)`, not the design cutoff.

**Pipeline, run read-only against the live catalog (`.scratch/c06-13f-momentum/pull_13f_legal.py`):**

- Queried all **14** 13F managers in `catalog.default_catalog()` via `service.load_delta(fund,
  as_of=dt.date(2025,11,14))`. All 14 returned a valid delta between period `2025-06-30` →
  `2025-09-30` (Pershing Square's delta had zero `NEW`/`ADD` rows — a genuinely quiet quarter, not a
  fetch failure).
- Pooled every `NEW`/`ADD` row (classification by share count only, per `deltas.diff`): **3,237**
  rows across the 14 managers.
- Resolved CUSIP → ticker via `catalog.ledger_cusip_tickers(settings)` (119 ledger entries): **134**
  of the 3,237 rows resolved to a ticker — about **4.1%**, consistent with the brief's ~3.7% sparsity
  estimate for the bridge over raw holdings generally.
- Intersected with the 173-symbol bar-store universe from `WINDOWS.md`: **85** of those 134 resolved
  rows had tradeable daily bars.
- **No fallback to issuer-name matching was used anywhere in this pipeline**, per the explicit
  prohibition in the assignment.

**What the 85 tradeable rows actually are.** Tallying by ticker across managers, the highest-
conviction names (companies for which multiple independent managers filed a `NEW` or `ADD` in the
same quarter) were: `GOOGL`(5 mgrs), `TSM`(5), `AMZN`(5), `META`(5), `MSFT`(5), `AMD`(4), `NVDA`(4),
`FIG`(4, all `NEW` — Figma's 2025 IPO), `AVGO`(4), then a tier at 3 managers (`GOOG`, `NET`, `QCOM`).
Every name above 3-manager conviction is a mega-cap technology or semiconductor name, or an ETF/fund
wrapper (`ARKK`, `GLD`, `SCHD`, `IGV`, `GGLL` also appeared at 1–2 managers and were dropped — a
13F-registered fund buying another fund is not the idiosyncratic-conviction signal this card is
built on).

**Final universe (8 names): `GOOGL, MSFT, AMZN, META, NVDA, AMD, AVGO, TSM`.**

Selection rule: the ≥4-manager-conviction single-name stocks, minus (a) `GOOG` — the same issuer as
`GOOGL`, already represented, and (b) `FIG` — despite 4-manager `NEW` conviction, Figma IPO'd
2025-07-31 and had only 76 daily bars before the window opens (2025-11-17); that is too little
history for a `sma(200)` trend filter to warm up on before the window starts, so it fails the
"universe fixed for the entire run, every symbol must have warmup before the window starts"
constraint on its own terms even though it passes the generic bar-availability guard. Checked
directly (read-only, `duck.connect(..., read_only=True)`): all 8 final tickers have **3,394 to
11,512** daily bars before 2025-11-17 — far in excess of the ~240 bars a `sma(200)` entry needs to
warm up plus the guard's 40-bar causality margin.

**Eligibility.** Per the assignment, this universe is legally knowable only from ~2025-11-14 onward,
so it is eligible for exactly **one** window: the special `13f-legal` window, 2025-11-17 →
2026-08-18. It is **not** eligible for any of the five main-matrix windows (`gfc`, `covid`,
`bear-2022`, `bull-2024`, `recent`) — none of those windows start after this universe's filing date,
and several predate the filing entirely. This card is therefore **unranked** in the main tournament
and reported only in the separate 13F track, as the assignment states in advance.

## 3. Parameters, against the budget of 10

| field | value | count |
|---|---|---|
| `entry`: `close > sma(200) and close crosses_above sma(20)` | literals `200`, `20` | 2 |
| `exit`: `close crosses_below sma(20)` | literal `20` | 1 |
| `stop_loss_pct` | `0.12` | 1 |
| `take_profit_pct` | `null` | 0 |
| `max_hold_days` | `null` | 0 |
| `max_positions` | `4` | 1 |
| `position_pct` | `0.20` | 1 |
| **Total** | | **6 / 10** |

`sma(20)` and `sma(200)` are conventional periods (short-term breakout confirmation against the
textbook long-term trend filter) — the same pair used to justify `sma(200)` in the brief itself.
`0.12` stop is a round number sized knowing (per §9 of the brief) that stops are checked against the
*previous close*, not the intraday low, so the realised loss on a stop-out will run worse than 12%.
`max_positions=4` / `position_pct=0.20` caps simultaneous exposure at 80% of starting equity (`4 ×
0.20 = 0.80 ≤ 1.001`), leaving headroom rather than committing the full book, and does not rely on
the round's relaxed 100% single-name cap.

## 4. What was measured in the design window, with actual numbers

All measurements below are in-sample (data through 2026-02-13, the design cutoff) and read-only —
**no backtest runner was invoked**, since `WINDOWS.md` states the runner takes an exclusive write
lock on the store and this round has other analysts working concurrently. Code:
`.scratch/c06-13f-momentum/` (`pull_13f.py`, `pull_13f_legal.py`, plus inline snippets reproduced
below).

**Signal frequency and forward returns**, `entry = close > sma(200) and close crosses_above sma(20)`,
full available history through 2026-02-13:

| symbol | bars | signals | mean fwd 20d | mean fwd 60d | % days above sma(200) | above sma(200) on 2026-02-13 |
|---|---|---|---|---|---|---|
| GOOGL | 5407 | 211 | +2.65% | +5.51% | 72.4% | yes |
| MSFT  | 10059 | 428 | +2.31% | +6.19% | 70.7% | **no** |
| AMZN  | 7233 | 258 | +4.68% | +13.45% | 66.4% | **no** |
| META  | 3455 | 161 | +1.50% | +5.49% | 75.3% | **no** |
| NVDA  | 6808 | 253 | +4.76% | +10.45% | 69.2% | yes |
| AMD   | 11573 | 344 | +1.87% | +6.19% | 51.7% | yes |
| AVGO  | 4157 | 194 | +2.60% | +8.08% | 78.6% | yes |
| TSM   | 7131 | 265 | +1.74% | +4.04% | 64.8% | yes |

Every symbol shows a positive mean forward return following the signal at both 20 and 60 sessions —
directionally consistent with the momentum thesis, though this is an in-sample, no-cost, unconditional
average over decades of a stock family that, by construction, survived to become mega-cap names (an
obvious survivorship bias worth naming rather than hiding). Note as of the design cutoff itself,
3 of 8 names (`MSFT`, `AMZN`, `META`) are **not** currently above their `sma(200)` — the rule is not
always-on even for this universe; it sat out roughly a quarter to a third of trading days historically
per name.

## 5. Sensitivity check

Per the brief's instruction to check for insensitivity rather than to grid-search for a winner: the
short/long SMA pair was re-run at all 9 combinations of short ∈ {15, 20, 25} × long ∈ {150, 200, 250}
on three of the eight names (`GOOGL`, `NVDA`, `AMD`), read-only, no parameter kept from this search:

- **GOOGL**: mean fwd-60d return ranged 4.63%–5.83% across all 9 combinations (signal count
  165–263). Sign and rough magnitude stable.
- **NVDA**: 8.90%–13.10% across all 9 combinations (signal count 238–296). Stable, always strongly
  positive.
- **AMD**: 4.47%–7.73% across all 9 combinations (signal count 297–411). Stable, always positive.

No combination flipped sign or collapsed to near zero. The rule survives this sensitivity check —
`sma(20)`/`sma(200)` was not a fitted pair; nearby round numbers behave the same way. (This is the
only place a "different setting" was ever computed; the submitted card uses the original 20/200, not
the best performer among the nine — GOOGL's best forward return in the grid was short=25/long=150,
which was not selected.)

## 6. What was tried and abandoned

- **Weighting the universe by cross-manager conviction count** (e.g., 5-manager names get more
  slots or larger `position_pct`) — abandoned because the engine has no cross-sectional weighting
  mechanism and the brief is explicit that ordering/weighting hacks are not expressible and, per the
  12-ordering sensitivity study cited in the brief (53.9-point spread from ordering alone), would be
  noise dressed as skill.
- **Including `FIG` (Figma) despite its 4-manager `NEW` conviction** — abandoned once its bar history
  was checked directly: only 76 daily bars before the window opens, insufficient for the `sma(200)`
  filter to be causally valid at window start even though the generic lookahead guard (which checks
  causality on the full history through 2026-02-13, not specifically before window start) does not
  catch this by itself. This is a real gap between what the guard checks and what the "universe must
  be knowable/tradeable at window start" constraint actually requires, worth flagging.
- **A tighter, RSI-based entry trigger** (e.g. `rsi(14) crosses_above 50` instead of the SMA
  breakout) — considered but not pursued: it added a parameter without changing the mechanism story,
  and the SMA breakout is the more standard, more easily defended convention for "price is confirming
  renewed buying."
- **Trying to widen the universe using issuer-name matching** for the ~96% of NEW/ADD rows that did
  not resolve via the CUSIP ledger bridge — not attempted at all, per the assignment's explicit
  prohibition on name-based CUSIP resolution.

## 7. Pre-registered failure regime

This card is a **concentrated bet on continued mega-cap AI/technology leadership**, not a
diversified 13F-conviction basket — that is what cross-manager conviction, once resolved through the
CUSIP bridge and the bar store, collapsed to (see §2 and §8). It is expected to lose in:

- **A rotation away from mega-cap tech** (into value, small-cap, or simply "the rest of the market"),
  even if the broad market is flat or up — the universe has no exposure outside this one theme.
- **A sharp, fast drawdown specific to AI/semiconductor names** — the `sma(200)` trend filter only
  removes exposure *after* the long-term average has rolled over, so it is structurally late to the
  start of any such move, and per the brief's own warning, the stop is checked against the previous
  close, not the intraday low, so a gap-down stop-out will realise worse than the nominal 12%.
- **A prolonged sideways chop** in these names — `close crosses_above sma(20)` will fire repeatedly
  on noise without the 60-day continuation the design-window measurement found historically, producing
  a string of small losses through the stop or the crosses-below exit.

## 8. Honest verdict: did the 13F step add anything measurable, or is this just momentum with an
   unusual universe?

**The second one, largely, and this is the genuinely useful finding from this assignment.** After the
mandatory pipeline — 14 real managers, share-count-only classification, the CUSIP-only ledger bridge
(resolving only ~4% of raw NEW/ADD rows, consistent with the brief's ~3.7% estimate), and intersection
with the bar store — the set of names with enough cross-manager conviction to be worth a fixed
universe collapsed almost entirely to the mega-cap technology / "Mag7 + semis" names that essentially
every growth-oriented institutional manager already owned and was adding to in Q3 2025 (`GOOGL`,
`MSFT`, `AMZN`, `META`, `NVDA`, `AMD`, `AVGO`, `TSM`). This is not a differentiated signal — it is the
single most crowded, most widely-known trade in the market over this period, arrived at through a
13F pipeline that looks rigorous but, once the ledger bridge's sparsity and the exclusion of ETF-like
holdings are applied, has very little room left to point anywhere else. A hypothetical universe built
from *raw* Google-search "smart money picks" would very likely have landed on nearly the same eight
names without needing EDGAR at all.

What the 13F step *did* contribute, concretely: it (a) forced a documented, mechanical, reproducible
selection process rather than a hand-picked list of familiar tickers, (b) surfaced and then correctly
excluded `FIG` on a real data constraint (insufficient warmup before window start) rather than on
narrative judgment, and (c) is falsifiable — a different quarter's 13F conviction tally could, in
principle, have surfaced a genuinely different, less crowded universe (a few 3-manager and 2-manager
names — `NET`, `QCOM`, `CRDO`, `OKLO`, `NBIS`, `IREN` — hint at more differentiated picks that fell
just short of the ≥4-manager conviction bar used here). The instrument works; what it revealed, in
this particular quarter and through this particular ledger's CUSIP coverage, is that resolvable 13F
conviction is dominated by consensus mega-cap tech, not a hidden-alpha basket. **If this card
outperforms in its one eligible window, the honest attribution is "momentum on mega-cap tech, with a
13F-sourced but effectively consensus universe" — not "13F selection found something the market
hadn't priced in."**

## 9. Weakest assumption

That share-count growth disclosed with a 45-day lag still predicts continued price-momentum months
later is untested here beyond the in-sample SMA-signal statistics in §4, which say something about
price-momentum persistence generally on these specific eight names, but nothing at all about whether
the 13F conviction step specifically added predictive value over just picking these same eight names
by market cap or index membership — no counterfactual "same rule, no-13F, generic mega-cap universe"
comparison was run (no backtest runner is available to this analyst without violating the store's
exclusive-write-lock rule during a live round), so §8's verdict is a structural/data argument, not a
measured performance delta.

## 10. Verbatim guard output

Command run exactly as specified in `BRIEF.md` §11:

```
cd "<repo>" && PYTHONPATH="backend;." .venv/Scripts/python.exe -c "
import sys, pathlib, datetime as dt; sys.path.insert(0,'backend')
from app.tournament.models import StrategyCard
from app.backtest.guards import check
from app.config import get_settings
from app.db import duck
AGENT='c06-13f-momentum'
card = StrategyCard.model_validate_json(
    pathlib.Path(f'strategy-program/rounds/r1-2026-08/cards/{AGENT}.json').read_text())
print('card OK:', card.agent_id, '| planned RRR:', card.reward_risk, '| slots:', card.max_positions)
s = get_settings()
with duck.connect(s.analytics_path, read_only=True) as conn:
    for sym in card.universe:
        bars = duck.read_bars(conn, s.bars_dir, sym, duck.Interval.DAY, end=dt.date(2026,2,13))
        for label, expr in (('entry', card.entry), ('exit', card.exit)):
            if expr.strip():
                st = check(expr, bars, interval=duck.Interval.DAY).status
                if str(st) != 'passed': print(' GUARD', st, sym, label)
    print('guard: all symbols checked')
"
```

Output:

```
card OK: c06-13f-momentum | planned RRR: None | slots: 4
guard: all symbols checked
```

No per-symbol `GUARD` failure lines were printed, for any of the 8 universe symbols, on either
`entry` or `exit` — the card and both expressions pass cleanly.
