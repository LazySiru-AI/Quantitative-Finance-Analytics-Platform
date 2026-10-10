# Analyst brief — Strategy Program, round 2

You are one of five analysts. You design **one** strategy, submit it, and it is then traded by
machinery you do not control across **eight market regimes** — two bear markets, a crash, a sharp
quarter-long selloff, two years of directionless chop, and two bull markets. You get one submission.

Read this whole brief before you touch any data.

## 0. What is different from round 1

Round 1 ran and produced findings. You are not told which cards won — that is quarantined, see §5 —
but everything methodological it established is below, and three things about the competition itself
have changed:

1. **Eight windows instead of five**, including **two genuinely sideways markets**. Round 1 had no
   directionless regime at all, while several analysts had named whipsaw as the thing they feared
   most. Those predictions went unscored. Now they can be scored.
2. **The ranking is no longer a single median.** See §1. A strategy with a convex payoff — small
   steady cost, large occasional payoff — was structurally ranked near-last by round 1's metric even
   when it was the best card in the crisis. That was a defect in the ranking, not in the card.
3. **The gate is five of eight windows**, up from three of five. Same proportion, more bite.

## 1. What you are optimising for

**The benchmark is SPY in every window** — price-only, bought at the window's first open, held to its
last close, the same convention your strategy gets. Each window carries its own SPY benchmark
computed over that window's own sessions.

For every window your card is eligible for:

```
excess          = return - benchmark_return
adjusted_excess = return - capital_exposure * benchmark_return
```

where `return` is `ending_equity / starting_equity - 1` and `capital_exposure` is the time-weighted
fraction of your **starting capital actually at risk** — not the fraction of sessions on which you
held something. A four-slot card holding one slot every session has a capital exposure near 25%, not
100%. Round 1 found the distinction changes conclusions and flips signs.

`adjusted_excess` asks whether your *rules* beat holding SPY with the same fraction of capital for
the same time. It exists because exposure otherwise dominates: an earlier tournament measured
Spearman **ρ = 0.648 between exposure and three-year return**.

**You are ranked three ways at once, and reported on all three:**

- **median** `adjusted_excess` across your eligible windows
- **worst window** — the one that would actually have happened to you
- **hit rate** — the fraction of windows with positive adjusted excess

Plus a Borda composite of the three, and a **Pareto frontier**: the set of cards that no other card
beats on all three at once. A card on that frontier is a defensible choice even if its median is
poor. **This means a deliberately convex strategy is now a viable submission** — one that costs a
little in most windows and pays a lot in one. It was not viable in round 1, which is why the rule
changed.

Spread across windows is reported too. A wide spread means the median is not describing anything.

## 2. Resist the urge to tune

The tournament preceding this program measured **Spearman ρ = 0.162 between in-sample return and
blind return**. How a strategy performed on the data its author studied told you almost nothing about
how it performed on data nobody had seen. Twenty of its 24 cards lost to the benchmark *on their own
design window* — the failure was not "brilliant in-sample, collapses after", most never managed the
first half.

- **A simple rule you can defend beats an optimised one you cannot.** If a parameter's value can only
  be justified by a backtest result, it is fitted.
- **Parameter budget: 10.** Count every number you chose: each numeric literal in `entry` and `exit`,
  plus `stop_loss_pct`, `take_profit_pct`, `max_hold_days`, `max_positions`, `position_pct`. Report
  your count. Hard limit. Round 1's submissions ranged 5 to 9; two analysts deliberately left
  headroom, which is a good instinct.
- **Do not grid-search.** Test sensitivity to show a rule is *insensitive*. A rule that works at
  `rsi(14) > 55` and breaks at `> 52` is fitted, and you should say so and choose something else.
- Prefer conventional periods. `sma(200)` is a convention thousands of participants actually watch,
  which is a mechanism. `sma(187)` is a search result.

## 3. The universe is open, and your choice of it has a consequence

**Pick your own symbols.** No assigned list. 173 symbols have readable daily bars; the full inventory
grouped by how far back each reaches is in `strategy-program/WINDOWS.md`. **Read that file** — it also
carries the window matrix you are being scored on.

Your `universe` is 1 to 12 tickers and is **fixed for the entire run**; the engine cannot rotate a
universe mid-window.

> **The gate: a card eligible in fewer than five of the eight main windows is unranked.**
> Not last — unranked, with its numbers published and excluded from the ranking.

A card can only run in a window where every symbol has enough history before it starts. Pick a 2024
listing and the GFC, both chop windows, `q4-2018` and `covid` all close to you at once — that is four
of eight gone, and the gate is unreachable. In round 1 **every single inherited card was locked out
of the GFC** because the field had been built from names that did not exist in 2008.

Nobody is telling you to pick old names. You are being told what a narrow, recent universe costs.

**Universe order is noise, not a lever.** When more symbols qualify than you have slots, the broker
fills in the order your `universe` array is written. Round 1 ran a card identical to another but for
that ordering: it differed by **up to 12.5 points in a single window**, and an earlier study measured
a 53.9-point spread across twelve orderings, σ = 21.2. Do not tune it and do not trust a result that
depends on it.

## 4. The data cutoff, and an honest limitation

**You may look at market data through 2026-02-13 and not one day further.** Enforced by the type
system: `StrategyCard` rejects a later `designed_through`. Bound every read with
`end=dt.date(2026,2,13)`.

**Round 2 is not an out-of-sample round, and you should know that.** No calendar time has passed
since round 1, so the cutoff has not advanced and no genuinely new data exists. This round widens the
*regimes* tested, it does not add unseen data. `bull-2024` and `recent` overlap your design period and
measure fit. The other six sit outside it — though you know a crisis window and a chop window are in
the matrix, which is itself a mild form of knowing. The report will say all of this.

If your universe is selected from a point-in-time document (a filing, an index reconstitution), you
must declare **`universe_knowable_from`** — the date that document became public. Any window starting
before it will be refused. Round 1's scorer ranked a 13F-derived card on four windows that all
predated its own filings, and no tool caught it.

## 5. Information quarantine — do not read these

Round 1's results would tell you which strategies won windows you are about to be scored on. **Do not
open:**

- `strategy-program/rounds/r1-2026-08/REPORT.md`, `.../reports/`, `.../analysis/`, `.../results/`
- `strategy-program/library/README.md` and anything under `strategy-program/library/`
- `docs/tournament/RESULTS.md`, `docs/tournament/RESULTS-3YR.md`, `docs/tournament/results/`
- `docs/research/strategy-lab/REPORT.md`

Everything you legitimately need from round 1 is in §7 of this brief. If you believe you need
something else from those documents, say so in your memo instead of reading it.

You may freely read `strategy-program/WINDOWS.md`, `strategy-program/CONSTRAINTS.md`, the harness
source under `backend/app/`, and any market data through the cutoff.

## 6. The card

One JSON file loading into `app.tournament.models.StrategyCard`. Extra fields are **forbidden**; the
model is frozen and strict.

| field | type | required | notes |
|---|---|---|---|
| `agent_id` | str | yes | Your assigned id exactly. |
| `display_name` | str | yes | Short human name. **ASCII only** — a round-1 card carried a mojibake character into every report that quoted it. |
| `discipline` | enum | yes | One of `trend`, `mean-reversion`, `momentum`, `breakout`, `volatility`, `pairs-rotation`, `risk-managed`. Yours is assigned. |
| `thesis` | str | yes | See §8. |
| `universe` | list[str] | yes | 1–12 tickers. |
| `entry` | str | yes | Rule DSL, must evaluate to boolean. |
| `exit` | str | yes | Rule DSL, or `""` if a target or time cap closes the position. |
| `stop_loss_pct` | decimal-as-string \| null | no | Fraction of one, e.g. `"0.08"`. |
| `take_profit_pct` | decimal-as-string \| null | no | Fraction of one. |
| `max_hold_days` | int \| null | no | 1–252. |
| `max_positions` | int | yes | 1–8. |
| `position_pct` | decimal-as-string | yes | Fraction of *starting* equity per position. |
| `designed_through` | ISO date | yes | `"2026-02-13"`. |

Two validators reject a card outright: `position_pct` must be in `(0, 1]` **and**
`position_pct * max_positions <= 1.001`; and at least one of `exit` (non-empty), `take_profit_pct` or
`max_hold_days` must be set.

## 7. The rule DSL, and what round 1 learned about execution

Grammar: `and` / `or` / `not`, parentheses, arithmetic `+ - * /`, comparisons `< <= > >= == !=`, and
`crosses_above` / `crosses_below`. Price fields usable bare: `open`, `high`, `low`, `close`, `volume`.
The expression **must terminate in a boolean**.

**Comparisons do not chain.** `close > sma(50) > sma(200)` fails; write
`close > sma(50) and sma(50) > sma(200)`.

Indicators, all confirmed against the parser on daily bars:

| call | params |
|---|---|
| `sma(period)` / `ema(period)` / `rsi(period)` / `atr(period)` | period 2–500 |
| `macd(fast,slow,signal)`, `macd_signal(...)`, `macd_hist(...)` | `fast < slow` required |
| `bb_upper(period,stddev)`, `bb_mid(...)`, `bb_lower(...)` | stddev may be integer or decimal |
| `swing_high(lookback)` / `swing_low(lookback)` | published `lookback` bars *after* the pivot forms |
| `rsi_at_swing_high(period,lookback)` / `rsi_at_swing_low(...)` | the other half of a divergence test |
| `macd_at_swing_high(f,s,sig,lookback)` / `macd_at_swing_low(...)` | same idea |

`vwap()` **fails on daily bars** — registered for intraday only. Not expressible at all: ADX,
stochastics, Ichimoku, volume profile, Fibonacci, cross-sectional ranking, per-symbol volatility
sizing, multi-timeframe confluence. There is **no way to gate one symbol on another's price** — every
expression is evaluated against that symbol's own bars, so "buy SPY when VIX is high" cannot be
written.

**Three execution findings from round 1 that should change how you design:**

1. **Stops fill far worse than nominal.** They are evaluated against the *previous close*, not the
   intraday low, then filled at the next open. Observed: a **10% stop that realised −22.81%**, and an
   8% stop that realised −18.22%. Size your risk knowing the stop does not cap the loss where you set
   it.
2. **A tighter stop is not obviously safer.** One card's 8% stop against its twin's 12% **more than
   doubled stop-outs, 10 against 4, without improving fill quality**, and on an identical position
   realised −17.00% where the looser stop realised −11.91%. In another window the tighter stop changed
   nothing at all — it relabelled eight exits from `rule` to `stop` without moving a single fill.
3. **Not trading during a crash is arithmetic, not skill.** Several cards scored well in `covid`
   purely because a trend-confirmation entry cannot fire mid-crash: they were absent for the fall and
   present for the recovery. The scorer's exposure adjustment now catches most of this, and the
   report will name it where it happens. If your card's defence is really absence, say so in your
   thesis rather than claiming risk management.

## 8. The thesis, and the pre-registration

State the **mechanism**: why the pattern exists, who is on the other side, and why they keep taking
it. Restating your own rules is not a thesis.

Then **name the regime you expect to lose in**, before it trades. The report prints your prediction
beside the outcome. In round 1, three of five analysts called their own worst window correctly and two
got it backwards, including one that named a window where it finished near flat while losing badly in
a window it never mentioned. This is a real test and it is scored.

With eight windows there is now no excuse for a prediction the matrix cannot evaluate — say which
*named window* you expect to be worst.

## 9. Execution reality

- Decisions use data strictly **before** the decision session; fills happen at the **next session's
  open**.
- Deterministic adverse slippage; commissions, SEC and TAF fees charged; whole shares only; $500
  minimum clip; T+1 settlement. Unaffordable entries are rejected and counted.
- **No dividends anywhere**, benchmark included. **Cash earns nothing** — sitting out is modelled as
  flat, which understates a real defensive position in a high-rate period.
- One stop and one position size for every symbol. No per-symbol volatility scaling.
- Long only. No shorts, no options.
- The persona's real 25% single-name cap is **raised to 100%** so cards run as written. If your
  `position_pct` exceeds 0.25 you are relying on that; say so.

## 10. Deliverables

Two files, yours alone. Do not create, edit, or read another analyst's files.

1. `strategy-program/rounds/r2-2026-08/cards/<your-agent-id>.json`
2. `strategy-program/rounds/r2-2026-08/memos/<your-agent-id>.md` — containing the mechanism; **why you
   chose your universe** and which of the eight windows it makes you eligible for; every parameter
   with its justification and your count against the budget of 10; what you measured in the design
   window, with numbers and the code you ran; any sensitivity check and whether the rule survived it;
   **the named window you expect to lose in**; and anything you tried and abandoned.

Use `.scratch/<your-agent-id>/` for working files.

## 11. Definition of done

```bash
cd "<repo>" && PYTHONPATH="backend;." .venv/Scripts/python.exe -c "
import sys, pathlib, datetime as dt; sys.path.insert(0,'backend')
from app.tournament.models import StrategyCard
from app.backtest.guards import check
from app.config import get_settings
from app.db import duck
AGENT='<your-agent-id>'
card = StrategyCard.model_validate_json(
    pathlib.Path(f'strategy-program/rounds/r2-2026-08/cards/{AGENT}.json').read_text())
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

**Every bar read must pass `read_only=True`.** The store is a single DuckDB file whose default
connection takes a write lock; concurrent analysts without that flag fail with an `IOException` that
looks exactly like a missing ticker.

## 12. Report back

The card as submitted, verbatim guard output, your parameter count, which of the eight windows you are
eligible for and why, **the named window you expect to lose in**, and the single weakest assumption in
your design.
